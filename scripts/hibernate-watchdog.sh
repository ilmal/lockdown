#!/bin/sh
# Backstop for a laptop that did not go down when the lid shut.
#
# Every automatic path on this laptop now leads to s2idle (lid -> suspend,
# idle -> suspend), which works. This timer exists for the day that stops
# being true, plus one hard floor:
#
#   - battery at or below 10% on battery power -> clean POWER OFF.
#     Not hibernate: on this machine hibernation hangs the kernel in a ~5 W
#     half-frozen state and drains ~9%/h while looking asleep, so it is
#     strictly worse than a clean shutdown at that point.
#
#   - lid shut for 10+ minutes and still running -> suspend failed; retry it
#     (the watchdog cannot hibernate, see above, and a retry is free).
#
#   - external display attached -> do nothing; that is "docked", matching
#     logind's HandleLidSwitchDocked=ignore.
#
# The systemd timer only fires while the machine is awake, so reaching the end
# of this script is itself proof the lid has been shut (or the battery has been
# low) for a whole interval without anything having taken the machine down.
set -eu

STATE=/run/presence-guard-hibernate-watchdog
GRACE=600
AC=/sys/class/power_supply/AC/online
BAT=/sys/class/power_supply/BAT0/capacity

[ -r "$AC" ] && [ -r "$BAT" ] || exit 0

on_ac=$(cat "$AC")
capacity=$(cat "$BAT")

# Hard floor: a clean power-off beats a hanging hibernate or a dead battery.
if [ "$on_ac" = "0" ] && [ "$capacity" -le 10 ]; then
    logger -t presence-guard-watchdog "battery at ${capacity}% on battery, powering off"
    rm -f "$STATE"
    exec systemctl poweroff
fi

# An attached external display means a shut lid is not a request to sleep;
# this mirrors logind's HandleLidSwitchDocked=ignore.
for status in /sys/class/drm/card*-*/status; do
    [ -r "$status" ] || continue
    case "$status" in *eDP*) continue ;; esac
    [ "$(cat "$status")" = "connected" ] && exit 0
done

lid=$(busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
        org.freedesktop.login1.Manager LidClosed 2>/dev/null | awk '{print $2}')

if [ "${lid:-false}" != "true" ]; then
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
    "lid shut for $(( (now - since) / 60 )) min and still running, retrying suspend"
rm -f "$STATE"
exec systemctl suspend
