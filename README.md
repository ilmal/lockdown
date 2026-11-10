# Lockdown

A laptop that checks it's still *you* sitting in front of it — and a button on
your phone that can power it off from anywhere.

<p align="center">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-black">
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="platform" src="https://img.shields.io/badge/platform-linux-lightgrey">
  <img alt="deps" src="https://img.shields.io/badge/cloud-none-brightgreen">
</p>

Everything runs locally: no cloud, no model downloads, no telemetry, no account.

---

## What it does

| | |
|---|---|
| 👁 **Presence check** | Every few minutes the camera looks for your face. Nobody there for too long → screen locks. |
| 🚫 **Impostor check** | Somebody *else* at the keyboard → locks on the second consecutive bad match. |
| 📱 **Remote lock** | Lock the machine from your phone over Tailscale. |
| ⚡ **Remote panic** | Lock, then power off — destroying the disk-encryption key held in RAM. |
| 😴 **Hibernate** | Power off while keeping every tab and terminal. |
| 🔌 **Fails safe** | Broken camera logs an error and keeps running; it never locks you out because hardware glitched. |

## The one idea worth understanding

Your disk is almost certainly **already encrypted**. The question after a theft
isn't "is the disk encrypted" — it's **"is the key still in RAM?"**

| Laptop was… | Can a thief read your data? | Lockdown's answer |
|---|---|---|
| Powered off | No — needs your passphrase | ✅ already safe |
| **Suspended** (lid shut) | **Yes** — key sits in RAM | ⚡ `panic` powers it off |
| Running and unlocked | Yes — they're already root | 📱 `lock` first |

So the most valuable thing a phone button can do is **power off**, not
"encrypt". That single insight is why this project has no destructive
"wipe the keys" endpoint — see [`docs/threat-model.md`](docs/threat-model.md).

---

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/presence-guard devices      # find your camera
.venv/bin/presence-guard enroll       # look at the laptop for a few seconds
.venv/bin/presence-guard check        # did it recognise you?
.venv/bin/presence-guard watch --dry-run   # watch it decide, without locking
```

When the dry run looks right, drop `--dry-run`.

## Use it

```console
$ presence-guard check
match: distance=41.2 threshold=62.0 face_area=34225

$ presence-guard watch
2026-11-10T09:14:02Z guard started: device=/dev/video0 interval=300s
2026-11-10T09:19:04Z present: distance 44.8 <= 62.0
2026-11-10T09:24:06Z absent: absent 0.4 min
2026-11-10T09:29:08Z LOCKED: nobody at the desk for 5.2 min (grace 5 min)
```

```console
# from your phone, on the tailnet
$ curl -H "Authorization: Bearer $TOKEN" http://<your-tailnet-ip>:8791/status
{"locked": false, "session": "2", "last_guard_event": null}

$ curl -X POST -H "Authorization: Bearer $TOKEN" http://<your-tailnet-ip>:8791/panic \
       -H 'Content-Type: application/json' -d '{"confirm":"panic"}'
{"action": "panic", "lock": "locked session 2", "poweroff": "requested"}
```

Add it to your phone with an iOS Shortcut or an Android widget —
[`docs/phone-setup.md`](docs/phone-setup.md).

---

## Features in detail

<details>
<summary><b>Face verification</b> — what it actually checks</summary>

```
camera frame → largest face → 100×100 greyscale crop → LBPH distance → threshold
```

Lower distance = closer match. `presence-guard calibrate` prints real distances
so you can tune the threshold instead of guessing:

```console
$ presence-guard calibrate
  0: distance=38.4
  1: distance=41.0
  2: distance=39.7
min=37.1 median=40.2 max=48.9
```

It needs ~25 samples and runs in milliseconds on a CPU.
</details>

<details>
<summary><b>Remote endpoints</b> — three actions, nothing destructive</summary>

| Method | Path | Does |
|---|---|---|
| `GET` | `/status` | Locked state, session id, last guard event |
| `POST` | `/lock` | Locks the session |
| `POST` | `/panic` | Locks, then powers off (needs `{"confirm":"panic"}`) |
| `POST` | `/hibernate` | Locks, then hibernates (needs `{"confirm":"hibernate"}`) |

Bearer token, compared in constant time, never logged. Binds to a single
Tailscale address — never `0.0.0.0`.
</details>

<details>
<summary><b>Hibernation</b> — power off without losing your session</summary>

RAM goes to swap, the machine powers off completely, and everything returns on
boot. Because swap lives *inside* the encrypted volume, the saved session is
encrypted too and still needs your passphrase.

```console
$ presence-guard hibernate --dry-run
hibernation is not usable on this machine:
  - swap is 8.0 GiB but RAM is 61.2 GiB
  - no resume device is configured
```

It refuses with the reasons rather than suspending and hanging.
`scripts/setup-hibernate.sh` does the setup and leaves a rollback script.
See [`docs/hibernate.md`](docs/hibernate.md).
</details>

<details>
<summary><b>Secret guard</b> — this repo is public, so pushes are checked</summary>

Three layers:

1. `scripts/check-secrets.sh` — private keys, cloud/API tokens, JWTs, tailnet
   IPs, personal paths, `password = "…"`.
2. `.githooks/pre-commit` — runs it on every commit.
3. `scripts/push.sh` — refuses to push unscanned changes.

```console
$ ./scripts/check-secrets.sh
  x leak.txt: matches /(password|passwd)[[:space:]]*[=:][[:space:]]*["']…/
Refusing to continue: the content above looks like a secret.
```

Pattern lists are a net, not a guarantee — the rule is still *no credentials in
this tree*.
</details>

---

## Design notes

**The IR camera lost.** This laptop has two sensors. I expected the IR one to
win; measurement said otherwise:

| Sensor | Frames with a face detected |
|---|---|
| RGB `/dev/video0` @640×480 | **10 / 10** |
| IR `/dev/video2` @640×360 | **3 / 10** |

Haar cascades are trained on visible-light faces, and an IR face is flat and
low-contrast. So RGB is the default. More in
[`docs/design-notes.md`](docs/design-notes.md).

**Honest limitations.** LBPH is a personal-project matcher, not a liveness
detector — it answers "is the enrolled person at the desk", not "is this a live
human". A printed photo may well pass. Its real value is that an unattended,
unlocked laptop locks itself.

## Docs

| | |
|---|---|
| [threat-model.md](docs/threat-model.md) | What each action does and doesn't protect |
| [remote-kill.md](docs/remote-kill.md) | Endpoint, token, polkit rule for poweroff |
| [phone-setup.md](docs/phone-setup.md) | iOS Shortcut / Android widget |
| [hibernate.md](docs/hibernate.md) | Session-preserving poweroff, and its traps |
| [design-notes.md](docs/design-notes.md) | Why these choices, measured not assumed |

## Requirements

Linux · Python 3.11+ · any UVC camera · Tailscale for the phone part.

## License

MIT
