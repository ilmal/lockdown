# Hibernation — keeping your session while killing the disk key

Poweroff protects the disk but loses your tabs. Hibernation gives you both:
the kernel writes RAM to swap, powers the machine fully off, and restores
everything on next boot.

**The security depends entirely on where swap lives.** If swap is on the
encrypted volume, the saved image is inside LUKS and restoring it still needs
your passphrase. If swap were on a plaintext partition, the whole session —
including whatever held the LUKS key — would be sitting readable on disk.

Check:

```bash
findmnt -no SOURCE /swap.img      # what backs the swap file
```

On this laptop `/swap.img` lives on `/dev/mapper/ubuntu--vg-ubuntu--lv`, which is
inside `dm_crypt-0`. So the hibernation image is encrypted at rest.

## Status on this laptop

Configured 2026-11-10 by `scripts/setup-hibernate.sh`:

| Requirement | Status |
|---|---|
| Kernel advertises `disk` | yes (`CONFIG_HIBERNATION=y`) |
| Swap ≥ RAM | **yes** — 65 GiB swap file, 61.2 GiB RAM |
| Resume device in kernel cmdline | **yes** — `resume=UUID=… resume_offset=…` |
| Resume module in initrd | **yes** — forced, because `74resume` self-disables at `0:0` |
| `/sys/power/resume` set | **yes** (`252:1`, matching `resume_offset=501760`) |

`vm.swappiness=1` keeps swap effectively unused except for hibernation.

**Everything above was already correct — and hibernation still failed.**
Measured 2026-11-20: every requirement passed while `systemctl hibernate`
returned `Access denied`. The blocker was not this machine's setup, it was
Ubuntu's polkit policy. See the next section.

### Ubuntu disables hibernation in polkit, not in the kernel

`policykit-desktop-privileges` ships
`/usr/share/polkit-1/rules.d/com.ubuntu.desktop.rules`, containing:

```javascript
// Disable hibernate by default in Ubuntu
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.upower.hibernate" ||
         action.id == "org.freedesktop.login1.hibernate" || ...) {
            return polkit.Result.NO;
    }
});
```

Confirm it on any machine:

```bash
pkcheck --action-id org.freedesktop.login1.suspend  --process $$   # authorized
pkcheck --action-id org.freedesktop.login1.hibernate --process $$   # Not authorized
systemctl hibernate                                                  # "Access denied"
```

`CanHibernate` likewise answers `"no"`. Note that `systemctl hibernate` failing
with **"Access denied"** rather than **"not supported"** is the useful
distinction: it proves the kernel-side checks in the table above all passed,
and only authorization was refused.

`scripts/install-hibernate-policy.sh` installs
`/etc/polkit-1/rules.d/00-lockdown-hibernate.rules`, which returns `YES` for
one user (and for root, which the authwatch service runs as). polkit evaluates
files by basename in lexical order and stops at the first rule function that
returns a value, so `00-` wins over the stock file without editing a
dpkg-owned path.


## This machine is dracut, not initramfs-tools

Ubuntu 26.04 boots a **dracut** initrd with `systemd-initrd`. Most hibernation
guides are written for initramfs-tools and write files nothing here reads
(`/etc/initramfs-tools/conf.d/resume` does not exist for dracut). The relevant
pieces:

- `/etc/dracut.conf.d/90-hibernate.conf` — `force_add_dracutmodules+=" resume "`
- `update-initramfs` is a **symlink to `/usr/sbin/update-initramfs` owned by the
  dracut package**; it is a dracut shim, so its flags are the dracut ones.
- The kernel cmdline comes from `/etc/default/grub`
  (`GRUB_CMDLINE_LINUX_DEFAULT`), plus drop-ins in `/etc/default/grub.d/`.

### Why the resume module must be forced

dracut's `74resume` `check()` returns 255 when `/sys/power/resume` is `0:0`,
which is exactly the state before hibernation is enabled. Without
`force_add_dracutmodules`, the module is dropped, the initrd has no
`systemd-hibernate-resume`, and hibernation powers off and then fails to
restore. Verify with:

```bash
lsinitrd /boot/initrd.img-$(uname -r) | grep systemd-hibernate-resume
```

## Fragmentation: expected here, and not fatal

The swap file spans **42 extents** and `e4defrag` cannot reduce it (measured).
The kernel's swapfile resume path uses the filesystem's block list rather than
assuming one contiguous run, so this works. The important safety property:

```
Unable to resume from device '%s' offset %lu, continuing boot process.
```

A resume that cannot find its image **boots normally instead of hanging**, so a
misconfiguration costs you the suspended session, not the machine.

## The trade-off, stated plainly

- Hibernate: session restored, key destroyed during the off period.
- Resume decrypts RAM using your passphrase at boot, so a thief who steals the
  powered-off machine still cannot read the image.
- Suspend (S3/s2idle): fastest, and the key stays in RAM — the thing you wanted
  to avoid.

This machine reports `s2idle` in `/sys/power/mem_sleep`, so a plain lid-close
suspend is the least safe of the three.

## If something goes wrong

`setup-hibernate.sh` writes `/root/hibernate-setup-<timestamp>/rollback.sh`,
which restores `/etc/fstab`, `/etc/default/grub`, removes the dracut and sysctl
drop-ins, recreates the 8 GiB swap file, and rebuilds the initrd and GRUB.

Do not edit the resume parameters by hand while debugging a lockout; run the
rollback instead.
