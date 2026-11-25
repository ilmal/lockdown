#!/bin/sh
# Hibernate a laptop whose lid is shut on battery but which is still running.
#
# A closed lid that is still awake is a failed suspend. logind retries a
# failing suspend for hours: on this laptop the NVIDIA PCI suspend callback
# returns -EIO whenever nvidia-suspend-then-hibernate.service has not run, so
# every attempt fails and the machine stays fully awake with the lid shut.
# Measured 2026-11-23: 74% -> 0% in about two and a half hours, ending in a
# hibernate that could not finish writing its image before the battery died.
#
# The systemd timer that runs this only fires while the machine is awake
# (WakeSystem is off, which is the default), so reaching the end of this script
# already proves the lid has been shut on battery for a whole interval.
set -eu

STATE=/run/presence-guard-hibernate-watchdog
GRACE=600
AC=/sys/class/power_supply/AC/online
BAT=/sys/class/power_supply/BAT0/capacity

[ -r "$AC" ] && [ -r "$BAT" ] || exit 0

# A battery at or below 10% is hibernated whatever the lid is doing.
if [ "$(cat "$AC")" = "0" ] && [ "$(cat "$BAT")" -le 10 ]; then
    logger -t presence-guard-watchdog "battery at $(cat "$BAT")% on battery, hibernating"
    exec systemctl hibernate
fi

# Docked: an external display attached means a shut lid changes nothing.
for s in /sys/class/drm/card*-*/status; do
    [ -r "$s" ] || continue
    case "$s" in *eDP*) continue ;; esac
    [ "$(cat "$s")" = "connected" ] && exit 0
done

lid=$(busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
        org.freedesktop.login1.Manager LidClosed 2>/dev/null | awk '{print $2}')

if [ "$(cat "$AC")" = "1" ] || [ "${lid:-false}" != "true" ]; then
    rm -f "$STATE"
    exit 0
fi

now=$(date +%s)
if [ -f "$STATE" ]; then
    since=$(cat "$STATE")
else
    echo "$now" > "$STATE"
    exit 0
fi

[ $((now - since)) -ge "$GRACE" ] || exit 0

logger -t presence-guard-watchdog \
    "lid shut on battery for $(( (now - since) / 60 )) min without suspending, hibernating"
rm -f "$STATE"
exec systemctl hibernate
