# Design notes

Short, and only the parts that are not obvious from the code.

## Camera choice: RGB, and why IR lost on this machine

`/dev/video0` is RGB (MJPEG + YUYV, up to 1280x720). `/dev/video2` is a separate
UVC sensor advertising **only 8-bit greyscale at 640x360** — the Windows Hello
IR camera. Two extension units sit in its chain
(`28f03370-…`, `0fb885c3-…`), i.e. the emitter is switched on and off through a
vendor UVC control, not through a normal `V4L2_CID_*`.

The plan was to use IR. Measurement said otherwise:

| Sensor | Face found |
|---|---|
| RGB `/dev/video0` @640x480 | 10/10 frames |
| IR `/dev/video2` @640x360 | 3/10 frames |

Haar cascades are trained on visible-light faces. An IR face is flat, dark and
low-contrast, so the same cascade that is rock-solid on RGB is a coin flip on
IR. A working IR pipeline needs a detector trained on IR imagery; that is a
model problem, not a resolution problem (the IR frame is also only 640x360, and
the face in it is ~45 px versus ~125 px on RGB).

So: RGB is the default. IR is documented as a possible upgrade, not a promised
feature. If you need to work in the dark, the cheap change is an external
near-IR-illuminated USB camera, not reusing this sensor.

## Why LBPH and not a deep face-embedding model

- Runs on CPU in milliseconds, no GPU, no model download, no network.
- Needs ~20 samples instead of thousands.
- Ships inside `opencv-contrib-python-headless`, so `pip install -e .` is the
  whole install.

Its weakness is honest: it is a texture histogram, not a liveness detector. It
answers "does this look like the enrolled person" and nothing more. See
`threat-model.md` for what that does and does not mean.

## Why the guard keeps running after an error

A watchdog that exits when its camera vanishes is worse than no watchdog: you
believe you are covered and you are not. Every exception is logged and the loop
sleeps again. The one thing it will not do is lock because the camera broke —
that turns a hardware glitch into a self-inflicted lockout.

## Why `panic` and not `destroy`

Encrypting is already done. The only thing that changes after theft is whether
the LUKS master key is still in RAM, and that changes on power-off. `destroy`
adds irreversible risk for no extra protection against the realistic threat.

## Token handling

- Read from a file outside the repo, mode 600.
- Compared with `hmac.compare_digest`.
- Never logged: `log_message` prints the request line only, and the bearer token
  lives in a header.
- Server binds to one Tailscale address, not `0.0.0.0`.

## Face recognition: YuNet + SFace, not LBPH

LBPH (the original implementation) is a 2004-era local-binary-pattern histogram.
Measured on this laptop: genuine scores ranged 62-83 on its distance scale with
the threshold at 62, so most checks said "impostor" for the right person.

Replaced with the pairing OpenCV ships for face recognition:

| | LBPH | YuNet + SFace |
|---|---|---|
| Detector | Haar cascade | YuNet (CNN) |
| Matcher | texture histogram | 128-D embedding, cosine |
| You | 62-83 (threshold 62) | **0.43-0.93** (threshold 0.40) |
| Stranger photo | — | **0.045** |
| Model size | 930 KB | 37 MB |
| Licence | BSD (OpenCV) | Apache-2.0 (OpenCV Zoo) |

### Alignment is the part that mattered

SFace expects landmark-aligned input. Feeding it a plain bounding-box crop made
a photo of a total stranger score **0.472 — i.e. a match**. Using YuNet's five
landmarks with `alignCrop` dropped the same photo to **0.045**.

Never compare embeddings from differently-cropped inputs: enrollment and
matching must both go through `alignCrop`.

### Why not dlib / face_recognition / insightface

- `face_recognition` (dlib) needs a 100 MB model plus a C++ build; accuracy is
  comparable to SFace and it is unmaintained.
- `insightface` (ArcFace) is the strongest open option and is what most
  production systems use, but it wants ONNX Runtime + ~300 MB of models and
  pulls a heavier dependency chain. Worth it if accuracy ever becomes the
  limiting factor; SFace's margin here is already wide.
- Commercial SDKs (Apple Vision, Luxand, Neurotechnology) are not needed for a
  "is the enrolled person at the desk" check.

The market standard for *liveness* (rejecting photos) is a different problem:
it needs depth, IR, or a trained anti-spoof model. This project does none of
that; see threat-model.md.

## HID bond for iPhone identity: built, then blocked by extended advertising

The plan: advertise as a BLE keyboard so iOS offers to bond; the bond exchanges
the phone's **Identity Resolving Key (IRK)**; BlueZ then resolves every rotating
address to the phone's stable identity forever. That is the only app-free,
beacon-free, battery-free route to "my phone is here".

`scripts/hid_peripheral.py` implements it: a HOGP keyboard service (0x1812 with
HID Information, Report Map, Report + Report Reference, Protocol Mode), Battery
and Device Information services, a NoInputNoOutput agent for Just Works pairing,
and an LEAdvertisement1 with appearance 0x03C1. Registration works, the agent
registers, and btmon confirms the packet goes on-air.

It is still invisible to the iPhone, and the reason is structural:

```
manager->extended_add_cmds = btd_has_kernel_features(KERNEL_HAS_EXT_ADV_ADD_CMDS);
...
if (client->manager->extended_add_cmds)
        return refresh_extended_adv(client, func);
return refresh_legacy_adv(client, func);
```

BlueZ 5.85 (src/advertising.c) chooses extended advertising purely on whether
the kernel supports the extended-advertising MGMT commands. There is no
per-advertisement override, no `Legacy` property on LEAdvertisement1 in 5.85,
and bluetoothctl's advertise menu has no toggle either. iOS's pairing list only
scans **legacy** advertisements, so an extended-only peripheral never appears in
Settings > Bluetooth — verified: btmon shows `LE Set Extended Advertising
Enable` with our "Lockdown Key" on-air, and the iPhone lists nothing.

Ways past it, ranked:

1. **A Bluetooth 4.x USB dongle.** A controller without extended-advertising
   support makes the kernel feature check fail, so BlueZ automatically takes the
   legacy path on that adapter. The iPhone then sees the keyboard, bonding
   works, and the IRK gives permanent identity. Cheap, reliable, zero phone
   battery. The recommended long-term fix.
2. **A small MGMT client** (`MGMT_OP_ADD_ADVERTISING`, the legacy kernel
   command) to place a legacy advertisement instance directly in the kernel,
   alongside the D-Bus GATT app. Works on this hardware with no purchase, but it
   is custom code that must run as root and be re-armed at boot.
3. Rebuild BlueZ with the legacy path forced — works, but replaces the system
   bluetoothd on the main laptop. Not recommended.

Note the phone-side reality that makes this all necessary: measured over a
3-minute capture, not one byte of a stock iPhone's Continuity advertisement is
stable across MAC rotation, and bonding (`bluetoothctl pair`) is refused with
`ConnectionAttemptFailed` — so nothing in the stock advertisement can identify
the phone.
