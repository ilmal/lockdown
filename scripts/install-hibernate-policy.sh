#!/usr/bin/env bash
# Configure hibernation policies:
#   1. lid closed       -> suspend, then hibernate after 35 min (systemd)
#   2. idle 35 min      -> hibernate (GNOME)
#   3. 3 failed logins  -> lock, then hibernate (authwatch service)
#
#   sudo scripts/install-hibernate-policy.sh
#
# Reversible: a rollback script is written next to a timestamped backup.
# Nothing is rebooted or hibernated here.
set -euo pipefail

STAMP=$(date +%Y%m%d-%H%M%S)
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BACKUP_DIR="/root/lockdown-hibernate-$STAMP"
TARGET_USER="${SUDO_USER:-nils}"
THRESHOLD="${LOCKDOWN_LOGIN_THRESHOLD:-3}"

POLKIT_RULE=/etc/polkit-1/rules.d/00-lockdown-hibernate.rules
SLEEP_DROPIN=/etc/systemd/sleep.conf.d/10-lockdown.conf
LOGIND_DROPIN=/etc/systemd/logind.conf.d/10-lockdown.conf
AUTHWATCH_UNIT=/etc/systemd/system/presence-guard-authwatch.service
AUTHWATCH_BIN=/usr/local/bin/presence-guard-authwatch
VENV_BIN="$REPO/.venv/bin/presence-guard"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ -x "$VENV_BIN" ] || { echo "missing $VENV_BIN; run: python3 -m venv .venv && .venv/bin/pip install -e ." >&2; exit 1; }

say() { printf '\n== %s\n' "$*"; }

# Run a command in the target user's graphical session, so gsettings writes to
# their dconf database rather than root's.
as_user() {
  local uid
  uid=$(id -u "$TARGET_USER")
  sudo -u "$TARGET_USER" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
    XDG_RUNTIME_DIR="/run/user/$uid" "$@"
}

say "backing up"
mkdir -p "$BACKUP_DIR"
for f in "$POLKIT_RULE" "$SLEEP_DROPIN" "$LOGIND_DROPIN" "$AUTHWATCH_UNIT" "$AUTHWATCH_BIN" \
         /etc/UPower/UPower.conf.d/90-critical-battery.conf \
         /etc/systemd/system/presence-guard-hibernate-watchdog.service \
         /etc/systemd/system/presence-guard-hibernate-watchdog.timer \
         /usr/local/bin/presence-guard-hibernate-watchdog; do
  [ -e "$f" ] && cp -a "$f" "$BACKUP_DIR/$(basename "$f")"
done
as_user gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type \
  > "$BACKUP_DIR/gsettings-ac-type" 2>/dev/null || true
as_user gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type \
  > "$BACKUP_DIR/gsettings-battery-type" 2>/dev/null || true
as_user gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout \
  > "$BACKUP_DIR/gsettings-ac-timeout" 2>/dev/null || true
as_user gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout \
  > "$BACKUP_DIR/gsettings-battery-timeout" 2>/dev/null || true
echo "backups in $BACKUP_DIR"

say "polkit: allow hibernation for $TARGET_USER and root"
# Ubuntu's /usr/share/polkit-1/rules.d/com.ubuntu.desktop.rules returns NO for
# every login1 hibernate action. Rules stop at the first function that returns
# a value, evaluated by basename in lexical order, so 00- wins over the stock
# file without modifying a dpkg-owned path.
install -Dm644 "$REPO/config/polkit-1/rules.d/00-lockdown-hibernate.rules" "$POLKIT_RULE"
sed -i "s/subject.user == \"nils\"/subject.user == \"$TARGET_USER\"/" "$POLKIT_RULE"

say "systemd: 35-minute hibernate delay"
install -Dm644 "$REPO/config/systemd/sleep.conf.d/10-lockdown.conf" "$SLEEP_DROPIN"

say "systemd: lid switch -> suspend-then-hibernate"
install -Dm644 "$REPO/config/systemd/logind.conf.d/10-lockdown.conf" "$LOGIND_DROPIN"
# The NVIDIA driver ships one hook per sleep operation, and only
# nvidia-suspend/-hibernate are enabled by default. Without this one the
# suspend-then-hibernate path never calls nvidia-sleep.sh, the GPU refuses the
# PCI suspend with -EIO, and every attempt fails while the machine stays awake
# with its lid shut. Measured 2026-11-23: 202 of 203 attempts failed and the
# battery went 73% -> 5%.
if systemctl list-unit-files nvidia-suspend-then-hibernate.service >/dev/null 2>&1; then
  systemctl enable nvidia-suspend-then-hibernate.service
fi

say "UPower: hibernate at 10% instead of 2%"
# At 2% there is not enough charge left to write the 10.6 GiB image, so the
# battery dies mid-hibernate and the next boot finds no image.
install -Dm644 "$REPO/config/UPower/UPower.conf.d/90-critical-battery.conf" \
  /etc/UPower/UPower.conf.d/90-critical-battery.conf
systemctl restart upower

say "backstop: hibernate a lid-shut machine that failed to suspend"
install -Dm755 "$REPO/scripts/hibernate-watchdog.sh" /usr/local/bin/presence-guard-hibernate-watchdog
install -Dm644 "$REPO/config/systemd/system/presence-guard-hibernate-watchdog.service" \
  /etc/systemd/system/presence-guard-hibernate-watchdog.service
install -Dm644 "$REPO/config/systemd/system/presence-guard-hibernate-watchdog.timer" \
  /etc/systemd/system/presence-guard-hibernate-watchdog.timer
systemctl daemon-reload
systemctl enable --now presence-guard-hibernate-watchdog.timer

say "GNOME: idle -> hibernate after 35 minutes"
# GNOME's idle monitor measures last input; logind's IdleActionSec only starts
# after the session reports itself idle, which lags by the blank-screen timeout.
# Setting these to hibernate is what makes "35 min without touching it" work.
as_user gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'hibernate'
as_user gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'hibernate'
as_user gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 2100
as_user gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 2100

say "authwatch: hibernate after $THRESHOLD failed logins"
cat > "$AUTHWATCH_BIN" <<EOF
#!/bin/sh
# Generated by scripts/install-hibernate-policy.sh
exec "$VENV_BIN" authwatch --threshold $THRESHOLD
EOF
chmod 755 "$AUTHWATCH_BIN"
install -Dm644 "$REPO/config/systemd/system/presence-guard-authwatch.service" "$AUTHWATCH_UNIT"
systemctl daemon-reload
systemctl enable --now presence-guard-authwatch.service

say "reloading logind"
# reload, never restart: logind is Type=notify-reload and its SIGHUP handler
# re-parses the whole config, whereas a restart tears down live sessions.
systemctl reload systemd-logind.service

say "writing rollback script"
cat > "$BACKUP_DIR/rollback.sh" <<EOF
#!/usr/bin/env bash
# Undo the hibernation policy installed on $STAMP.
set -euo pipefail
systemctl disable --now presence-guard-authwatch.service || true
systemctl disable --now presence-guard-hibernate-watchdog.timer || true
systemctl disable nvidia-suspend-then-hibernate.service || true
rm -f "$AUTHWATCH_UNIT" "$AUTHWATCH_BIN" "$POLKIT_RULE" "$SLEEP_DROPIN" "$LOGIND_DROPIN"
rm -f /etc/UPower/UPower.conf.d/90-critical-battery.conf
rm -f /etc/systemd/system/presence-guard-hibernate-watchdog.service
rm -f /etc/systemd/system/presence-guard-hibernate-watchdog.timer
rm -f /usr/local/bin/presence-guard-hibernate-watchdog
systemctl restart upower
systemctl daemon-reload
systemctl reload systemd-logind.service
uid=\$(id -u "$TARGET_USER")
restore() {
  sudo -u "$TARGET_USER" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/\$uid/bus" \\
    XDG_RUNTIME_DIR="/run/user/\$uid" gsettings set org.gnome.settings-daemon.plugins.power "\$1" "\$2"
}
[ -f "$BACKUP_DIR/gsettings-ac-type" ] && restore sleep-inactive-ac-type "\$(cat "$BACKUP_DIR/gsettings-ac-type")"
[ -f "$BACKUP_DIR/gsettings-battery-type" ] && restore sleep-inactive-battery-type "\$(cat "$BACKUP_DIR/gsettings-battery-type")"
[ -f "$BACKUP_DIR/gsettings-ac-timeout" ] && restore sleep-inactive-ac-timeout "\$(cat "$BACKUP_DIR/gsettings-ac-timeout")"
[ -f "$BACKUP_DIR/gsettings-battery-timeout" ] && restore sleep-inactive-battery-timeout "\$(cat "$BACKUP_DIR/gsettings-battery-timeout")"
echo "rolled back"
EOF
chmod +x "$BACKUP_DIR/rollback.sh"

say "verification"
printf -- '--- polkit (must not say "Not authorized") ---\n'
pkcheck --action-id org.freedesktop.login1.hibernate --process $$ && echo "authorized" || echo "STILL DENIED" >&2
printf -- '--- logind capabilities ---\n'
for m in CanHibernate CanSuspendThenHibernate; do
  printf '%-26s %s\n' "$m" \
    "$(busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager "$m")"
done
printf -- '--- effective sleep config ---\n'
systemd-analyze cat-config systemd/sleep.conf | grep -vE '^#|^$' || true
printf -- '--- effective lid switch ---\n'
systemctl show systemd-logind -p HandleLidSwitch -p HandleLidSwitchExternalPower -p HandleLidSwitchDocked 2>/dev/null || true
printf -- '--- authwatch ---\n'
systemctl is-active presence-guard-authwatch.service || true

cat <<EOF

Done. Not rebooted and not hibernated.

Test, in order:
  1. .venv/bin/presence-guard hibernate      # must reach "hibernated", not "Access denied"
  2. close the lid, then watch:  journalctl -f -g 'PM:'   # suspend, then hibernation
  3. sudo .venv/bin/presence-guard authwatch --dry-run --threshold 1
     then fail one login and watch it announce the action

If anything misbehaves:  sudo $BACKUP_DIR/rollback.sh

Note: HibernateMode is "shutdown" instead of "platform" because this laptop's
firmware fails ACPI S4 with "Device or resource busy". In shutdown mode the
kernel writes the image and does a clean power-off; resume still works via
the initrd's resume=/resume_offset check.
EOF
