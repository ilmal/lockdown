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
