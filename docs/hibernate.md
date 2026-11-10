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
inside `dm_crypt-0`. So hibernating is safe here, **once it is set up**.

## Current state of this machine

Not usable yet. Measured:

| Requirement | Status |
|---|---|
| Kernel advertises `disk` in `/sys/power/state` | yes |
| Swap ≥ RAM | **no** — 8 GiB swap vs 61 GiB RAM |
| Resume device configured | **no** — `/sys/power/resume` is `0:0` |

`presence-guard hibernate` runs exactly these checks and refuses with the list
of reasons rather than suspending and hanging.

## Making it work

1. **Grow swap to more than RAM.** With 61 GiB of RAM this is a 62+ GiB file,
   and it must be contiguous enough for the kernel's resume code. On this box
   there is 1.6 TiB free, so size is not the obstacle. A swap *file* works on
   Ubuntu (the kernel supports `resume=` on a file since 5.x) but a dedicated
   LVM logical volume is simpler to point at.
2. **Tell the kernel and initramfs where the image is**, e.g. in
   `/etc/default/grub`:
   ```
   GRUB_CMDLINE_LINUX_DEFAULT="... resume=/dev/mapper/ubuntu--vg-swap"
   ```
   plus `RESUME=/dev/mapper/ubuntu--vg-swap` in
   `/etc/initramfs-tools/conf.d/resume`, then `update-grub` and
   `update-initramfs -u -k all`.
3. **Verify** with `systemctl hibernate` once, while nothing important is open.
   A failed first attempt can leave the machine unbootable until you fix the
   resume parameters from a live USB.

Do that setup deliberately, not while debugging a lockout. Until then, `panic`
(poweroff) is the only action that guarantees the LUKS key is gone.

## The trade-off, stated plainly

- Hibernate: session restored, key destroyed during the off period.
- Resume-from-hibernate decrypts RAM using your passphrase at boot, so a thief
  who steals the powered-off machine still cannot read the image.
- Suspend (S3/s2idle): fastest, and the key stays in RAM — the thing you wanted
  to avoid.

This machine currently reports `s2idle` in `/sys/power/mem_sleep`, so a plain
lid-close suspend is the least safe of the three.
