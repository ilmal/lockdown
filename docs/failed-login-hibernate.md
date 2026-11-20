# Failed logins → hibernate

Three failed password attempts lock the screen and hibernate the machine, so
the disk-encryption key leaves RAM instead of sitting there for whoever has
the laptop.

## Why the journal, and not `pam_faillock`

`pam_faillock` is the usual answer, and it is the wrong one here. It has to be
spliced into `common-auth`, which every service includes:

```console
$ grep -l common-auth /etc/pam.d/*
cron  polkit-1  runuser  sddm  sshd  su  sudo  ...
```

A mistake in that stack costs you `sudo` *and* the ability to log in, at the
same time, on a machine whose only other way in is a LUKS passphrase at the
boot prompt. The failure count is therefore read from log lines that `pam_unix`
already writes, and no PAM file is touched.

## What counts

`presence-guard-authwatch` follows the journal and counts failures per user:

| Service | Covers |
|---|---|
| `gdm-password` | GDM greeter login **and** the GNOME lock screen (both authenticate through this one service) |
| `login` | `Ctrl+Alt+F2` text console |
| `sudo` | `sudo` password prompts |
| `sshd` | SSH — inert here, since `PasswordAuthentication no` means pam_unix never sees a password |

Three failures within 10 minutes hibernate. A successful login for that user
resets the count. Failures older than the window are dropped, so three
mistakes spread over an afternoon do not accumulate.

`cron` opens a session for `nils` every 15 minutes; it is excluded by name,
because counting it as a success would reset the counter before it ever
reaches three.

## Running it

The service is root-only, and it must be: the interesting case is failed logins
**at the greeter**, when no user session exists at all and a user-level process
would be unable to hibernate the machine.

```bash
sudo scripts/install-hibernate-policy.sh      # installs and enables it
systemctl status presence-guard-authwatch
journalctl -u presence-guard-authwatch -f     # "failed login for nils: 2/3"
```

To watch it decide without hibernating:

```bash
sudo .venv/bin/presence-guard authwatch --dry-run --threshold 1
```

then fail one login.

## The threshold is "more than 2", i.e. 3

`--threshold 3` means the third failure acts. Set `LOCKDOWN_LOGIN_THRESHOLD` to
change it at install time.
