# presence-guard

Continuous face-presence verification for a laptop, plus a phone-activated
kill switch.

Two independent parts:

1. **Local presence guard** — every few minutes, capture a frame from the
   laptop's camera, check that a known face is in front of it. If nobody is
   there for long enough, lock the screen. If somebody *else* is there, lock
   immediately and alert.
2. **Remote kill switch** — a token-authenticated HTTP endpoint reachable only
   over your Tailscale tailnet. From your phone you can lock the session, or
   power the machine off so the LUKS master key is no longer in RAM.

Everything runs locally. No cloud, no model downloads, no telemetry.

## Read this before enabling the kill switch

The disk is *already* encrypted (LUKS2). There is no "remote encrypt" to
perform. The realistic attack after a laptop is stolen is:

| Laptop was… | What protects you |
|---|---|
| powered off / shut down | LUKS passphrase. Already fine. |
| suspended (lid closed) | **Nothing.** RAM stays powered, the LUKS key sits in it. A cold-boot or DMA attack recovers it. |
| on and unlocked | **Nothing.** Attacker is already root. |

So the single most valuable remote action is **poweroff**: it destroys RAM
contents and therefore the in-memory LUKS key. Next boot asks for the
passphrase again, exactly as you want.

`panic` does that safely and reversibly. A true "make the disk unreadable"
action would mean wiping LUKS keyslots, which is **irreversible** — this repo
deliberately ships no such endpoint and no config for one. See
`docs/threat-model.md` for why, and for the header-backup step to take before
anyone ever writes one.

## Safety defaults

- No endpoint deletes keys, edits `/etc/crypttab`, or touches `/etc/fstab`. The
  worst thing a misaimed request can do is power the laptop off.
- `panic` requires an explicit confirmation body, not just a POST.
- Every CLI action that touches the session accepts `--dry-run` and prints the
  exact command it would run.
- The remote server refuses to start without a token file and binds to one
  Tailscale address, never `0.0.0.0`.

## Install

```bash
cd ~/programing/presence-guard
python3 -m venv .venv
.venv/bin/pip install -e .
```

Install the CLI on your PATH (optional):

```bash
.venv/bin/pip install --user -e .
```

## Enroll your face

Enrollment is a one-time, interactive step. It writes only to
`~/.local/share/presence-guard/`, never into this repo.

```bash
presence-guard enroll --samples 25
```

Sit in front of the laptop, look at it normally. It will capture frames from
the IR camera, detect your face, and save normalised crops.

Then check that verification recognises you:

```bash
presence-guard check --verbose
```

## Run the guard

```bash
presence-guard watch --dry-run      # observe only, never locks
presence-guard watch                # for real
```

Install as a user service (runs while you are logged in):

```bash
mkdir -p ~/.config/systemd/user
cp systemd/presence-guard.service systemd/presence-guard-remote.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now presence-guard.service presence-guard-remote.service
```

## Remote control from your phone

The remote server binds **only** to your Tailscale address, so it is not
reachable from any network you are not already on. Generate a token first:

```bash
mkdir -p ~/.claude/secrets
head -c 32 /dev/urandom | base64 > ~/.claude/secrets/presence-guard-token
chmod 600 ~/.claude/secrets/presence-guard-token
```

Then from your phone (Tailscale connected):

```bash
TOKEN=$(cat ~/.claude/secrets/presence-guard-token)

curl -H "Authorization: Bearer $TOKEN" http://100.x.y.z:8791/status
curl -X POST -H "Authorization: Bearer $TOKEN" http://100.x.y.z:8791/lock
```

`panic` — lock, then power off:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"confirm":"panic"}' \
     http://100.x.y.z:8791/panic
```

Bookmark that on the phone, or see `docs/phone-setup.md` for an iOS Shortcut.

## Configuration

Config lives at `~/.config/presence-guard/config.toml` (see
`config.example.toml`). Nothing in this repo is machine-specific.

## Requirements

- Linux with a UVC camera
- Python 3.11+
- OpenCV contrib (`opencv-contrib-python-headless`, installed by `pip install -e .`)
- For the remote part: Tailscale reachable from your phone
- For poweroff without a password prompt: a polkit rule or a narrow sudoers
  entry — see `docs/remote-kill.md`

## The IR camera: measured, not assumed

This laptop (Dell Precision 5570) has **two** UVC sensors. `/dev/video0` is RGB
(up to 1280x720, MJPEG/YUYV). `/dev/video2` is a second sensor that exposes only
8-bit greyscale at 640x360 — the Windows Hello IR camera.

I expected IR to be the better choice. Measured on this machine, it is not:

| Sensor | Frames with a detected face |
|---|---|
| `/dev/video0` RGB @640x480 | **10 / 10** |
| `/dev/video2` IR @640x360 | **3 / 10** |

The Haar detector shipped here is trained on visible-light faces, and an IR face
is a flat, dark, low-contrast version of one. The default configuration
therefore uses **RGB**. IR remains genuinely better in the dark and is harder to
spoof with a phone screen — if you want it, expect to swap in a detector trained
on IR, which is real work, not a config flag.

## Limitations, stated honestly

- LBPH face matching is a personal-project-grade matcher. It is not a
  security boundary against a determined attacker who already has physical
  access; it is a check that *the person at the desk is still you*.
- IR defeats a phone screen and a printed photo far better than RGB does, but
  it is not a certified liveness detector.
- If the laptop is offline or powered off, the remote endpoint cannot reach it.
  The local presence guard is the backstop for that case.

## License

MIT
