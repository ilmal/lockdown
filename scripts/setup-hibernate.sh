#!/usr/bin/env bash
# Set up hibernation on Ubuntu 26.04 with a LUKS-encrypted root (dracut initrd).
#
#   sudo scripts/setup-hibernate.sh [SWAP_SIZE]      # default 65G
#
# Reversible: a rollback script is written to $BACKUP_DIR and the old
# grub.cfg / fstab / initrd are kept. Nothing is rebooted or hibernated here.
#
# Why a swap FILE and not a swap LV: the volume group has no free extents, so
# an LV would mean shrinking the 1.8T root. A file is the safe route.
#
# The resume target must be the DECRYPTED root mapping. Because swap lives on
# LUKS+LVM, resume only works after the initrd has unlocked the volume, which
# is why the kernel needs resume=<root uuid> resume_offset=<first extent>.
set -euo pipefail

SWAP_FILE=/swap.img
SIZE="${1:-65G}"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/root/hibernate-setup-$STAMP"
DRACUT_CONF=/etc/dracut.conf.d/90-hibernate.conf
SYSCTL_CONF=/etc/sysctl.d/99-hibernation.conf

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

say() { printf '\n== %s\n' "$*"; }

fs_uuid() { blkid -s UUID -o value "$1"; }

ROOT_MAPPER=$(findmnt -no SOURCE /)
ROOT_UUID=$(fs_uuid "$ROOT_MAPPER")
CURRENT_SIZE=$(swapon --show=NAME,SIZE --noheadings --bytes 2>/dev/null | awk -v f="$SWAP_FILE" '$1==f{print $2}')
MEM_BYTES=$(awk '/MemTotal/{print $2*1024}' /proc/meminfo)

say "preconditions"
[ -n "$ROOT_UUID" ] || { echo "cannot read root filesystem UUID" >&2; exit 1; }
[ "$(findmnt -no FSTYPE /)" = "ext4" ] || { echo "root is not ext4" >&2; exit 1; }
printf 'root mapper : %s\nroot uuid   : %s\nram         : %.1f GiB\nswap now    : %s bytes\n' \
  "$ROOT_MAPPER" "$ROOT_UUID" \
  "$(awk -v b="$MEM_BYTES" 'BEGIN{print b/1073741824}')" "${CURRENT_SIZE:-none}"

say "backing up"
mkdir -p "$BACKUP_DIR"
cp -a /etc/fstab "$BACKUP_DIR/fstab"
cp -a /etc/default/grub "$BACKUP_DIR/grub"
cp -a /boot/grub/grub.cfg "$BACKUP_DIR/grub.cfg"
swapon --show > "$BACKUP_DIR/swapon.txt" 2>&1 || true
echo "$ROOT_UUID" > "$BACKUP_DIR/root-uuid"
echo "backups in $BACKUP_DIR"

say "creating $SIZE swap file"
swapoff "$SWAP_FILE" 2>/dev/null || true
rm -f "$SWAP_FILE"
# dd (not fallocate) so the blocks are actually written; either way the file
# will span several extents on this filesystem.
dd if=/dev/zero of="$SWAP_FILE" bs=1M count=$(( ${SIZE%G} * 1024 )) status=progress
chmod 600 "$SWAP_FILE"

EXTENTS=$(filefrag "$SWAP_FILE" | sed -n 's/.*: \([0-9]*\) extent.*/\1/p')
echo "swap file extents: ${EXTENTS:-unknown}"
if [ "${EXTENTS:-1}" -gt 1 ]; then
  # Not fatal: the kernel's swapfile resume walks the filesystem for the
  # blocks. e4defrag cannot coerce this filesystem into one extent (measured
  # 37-40 extents at 65G), so a single extent is not achievable here.
  echo "NOTE: $SWAP_FILE spans $EXTENTS extents; resume will use the block list."
  echo "      If resume ever fails, boot continues normally (no bricking)."
fi

mkswap "$SWAP_FILE" >/dev/null
swapon "$SWAP_FILE"

# The kernel takes resume_offset in filesystem BLOCKS (ext4 blocksize units),
# which is the first physical extent's start offset.
RESUME_OFFSET=$(filefrag -v "$SWAP_FILE" \
  | awk '$1=="0:" { off=$4; sub(/\.+$/,"",off); print off; exit }')
[ -n "$RESUME_OFFSET" ] || { echo "could not determine resume_offset" >&2; exit 1; }
echo "resume_offset: $RESUME_OFFSET"

say "keeping swap for hibernation only"
printf 'vm.swappiness=1\n' > "$SYSCTL_CONF"
sysctl -q -w vm.swappiness=1

say "ensuring dracut ships the resume module"
# dracut's 74resume check() returns 255 when /sys/power/resume is 0:0, which
# silently drops the module and leaves hibernation unable to resume.
# force_add bypasses that check.
printf 'force_add_dracutmodules+=" resume "\n' > "$DRACUT_CONF"

say "adding resume= to the kernel command line"
CMDLINE="resume=UUID=$ROOT_UUID resume_offset=$RESUME_OFFSET"
if grep -q 'resume=UUID=' /etc/default/grub; then
  sed -i -E "s|resume=UUID=[^ \"]*|resume=UUID=$ROOT_UUID|" /etc/default/grub
  sed -i -E "s|resume_offset=[0-9]*|resume_offset=$RESUME_OFFSET|" /etc/default/grub
else
  sed -i -E "s|^(GRUB_CMDLINE_LINUX_DEFAULT=\")(.*)\"$|\1\2 $CMDLINE\"|" /etc/default/grub
fi
grep '^GRUB_CMDLINE_LINUX_DEFAULT' /etc/default/grub

say "rebuilding initrd and grub"
if [ -e "/boot/initrd.img-$(uname -r)" ]; then
  cp -a "/boot/initrd.img-$(uname -r)" "$BACKUP_DIR/initrd.img.keep"
fi
update-initramfs -u -k all >/dev/null 2>&1 || dracut --force
update-grub >/dev/null 2>&1

# Hibernation with a LUKS-encrypted root only resumes because /boot is
# UNENCRYPTED: the initrd unlocks the volume, then the resume image is read
# from swap afterwards. If /boot ever moves inside the encrypted volume, the
# resume image would live on the volume it is trying to write into, and
# resume would deadlock. Fail loudly if that ever becomes true.
BOOT_SRC=$(findmnt -no SOURCE /boot)
if findmnt -no FSTYPE "$BOOT_SRC" 2>/dev/null | grep -q crypto_LUKS; then
  echo "ERROR: /boot is inside LUKS; hibernation cannot safely resume." >&2
  exit 1
fi

say "writing rollback script"
cat > "$BACKUP_DIR/rollback.sh" <<EOF
#!/usr/bin/env bash
# Undo the hibernation setup performed on $STAMP.
set -euo pipefail
cp -a "$BACKUP_DIR/fstab" /etc/fstab
cp -a "$BACKUP_DIR/grub" /etc/default/grub
rm -f "$DRACUT_CONF" "$SYSCTL_CONF"
swapoff $SWAP_FILE 2>/dev/null || true
rm -f $SWAP_FILE
fallocate -l 8G $SWAP_FILE
chmod 600 $SWAP_FILE
mkswap $SWAP_FILE >/dev/null
swapon $SWAP_FILE
update-initramfs -u -k all || dracut --force
update-grub
echo "rolled back; reboot to restore the previous boot behaviour"
EOF
chmod +x "$BACKUP_DIR/rollback.sh"

say "verification"
printf -- '--- swap ---\n'; swapon --show
printf -- '--- extents ---\n'; filefrag "$SWAP_FILE"
printf -- '--- grub cmdline ---\n'; grep -o 'resume[^ ]*' /boot/grub/grub.cfg | sort -u
printf -- '--- initrd resume support ---\n'
# Note: capture first, then grep. `lsinitrd | grep -q` under `set -o pipefail`
# fails spuriously: grep -q exits early, lsinitrd dies on SIGPIPE, and pipefail
# reports the pipeline as failed even when the match succeeded.
INITRD_LIST=$(lsinitrd "/boot/initrd.img-$(uname -r)" 2>/dev/null || true)
case "$INITRD_LIST" in
  *systemd-hibernate-resume*)
    echo "resume helper present in initrd" ;;
  *)
    echo "WARNING: resume helper NOT found in the new initrd." >&2
    echo "         Hibernation would power off but fail to resume." >&2
    echo "         Check $DRACUT_CONF and the dracut output above." >&2 ;;
esac

cat <<EOF

Done. Not rebooted and not hibernated.

Next:
  1. reboot  (or at least log out) so the kernel picks up resume=
  2. verify:  cat /sys/power/resume   # must be non-zero, e.g. 259:3
  3. test:    presence-guard hibernate
  4. if anything misbehaves:  sudo $BACKUP_DIR/rollback.sh

Note: recreating $SWAP_FILE changes resume_offset. Re-run this script
(rather than only mkswap) if you ever resize or replace the swap file.
EOF
