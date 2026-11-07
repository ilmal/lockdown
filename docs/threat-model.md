# Threat model — what each action actually buys you

The disk on this laptop is LUKS2 encrypted (`cryptsetup 2.8.4`, TPM 2.0
present). Encryption is not a switch to flip; it is already on. What varies is
**where the master key is**.

## Where the LUKS key lives

| State | RAM powered? | Key recoverable from the machine? |
|---|---|---|
| Powered off | no | no — needs your passphrase |
| Suspended (S3) | yes | **yes**, via cold-boot or DMA |
| Hibernated | no | no |
| Running, screen locked | yes | **yes** — attacker has root |

That table is the whole design constraint. Locking the screen is an
*account* boundary, not a *disk* boundary.

## What the remote switch can do

Actions are listed from safe to dangerous. Only the first two are reachable
without opt-in.

### `lock`
Locks the session. Stops a casual passer-by. Does **not** protect the disk —
the key stays in RAM. Cheap and fully reversible.

### `panic` (recommended)
Locks, then powers off. Powering off is the real win: it wipes RAM, so the
LUKS master key is gone and the next person needs your passphrase. This is the
action that matters, it is reversible, and it is what the phone button should
call.

Caveat: it needs unprivileged `loginctl poweroff` to work while you are logged
in. `docs/remote-kill.md` covers the two ways to grant that without handing out
blanket root.

### `destroy` (disabled by default, irreversible)
Would wipe the LUKS keyslots, making the volume permanently unreadable. The
toolkit ships this **only as documentation** — `presence_guard.destructive` is
deliberately absent from the CLI, because a bug in an agent-written script must
never be able to make your laptop unrecoverable while you are testing it from
your phone.

If you ever do want it, write the four lines yourself, run them once on a
throwaway VM first, and keep an off-device LUKS header backup:

```bash
# DO NOT RUN THIS FROM A SCRIPT YOU HAVE NOT READ END TO END
sudo cryptsetup luksHeaderBackup /dev/nvme0n1p3 \
    --header-backup-file ~/luks-header-$(date +%F).img
```

That backup is the only thing that can undo a keyslot wipe, and it is itself
sensitive — it accepts your passphrase. Store it offline.

## What an attacker who *has* the laptop can beat

- A printed photo held to the camera — partially defeated: Haar detection on a
  photo usually works, so this needs liveness checks that are **not** in this
  project yet. IR would help here, but the detector currently runs on RGB (see
  `design-notes.md`).
- A phone showing a photo — same story.
- A latex fingerprint / enrolled face model — not addressed; LBPH is not
  liveness detection.
- Someone who reboots into a live USB — the disk stays encrypted, which is the
  point.
- Someone who reads the RAM of a running or suspended machine — defeated only
  by `panic`.

Be clear-eyed: the presence guard answers "is the enrolled person at the desk",
not "is this a live human". Its real value is that a laptop left unattended in a
cafe with you logged in will lock itself, and a remote `/panic` destroys the
in-RAM LUKS key.

## Failure modes worth knowing

- **Camera disappears** (unplugged, driver crash): the guard logs `ERROR`
  every interval and keeps running. It will **not** lock you out because a
  device vanished — that would be a remote DoS on yourself.
- **No face, forever**: locks after `absent_grace_minutes`. If you are away from
  the laptop for a long meeting, this is desirable.
- **Laptop offline**: the phone cannot reach it. The presence guard still runs
  locally.
- **You get locked out of your own machine**: this design never changes
  `/etc/crypttab`, `/etc/fstab`, or any keyslot. Recovery from anything the tool
  does is "unlock normally".
