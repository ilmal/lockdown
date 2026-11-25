#!/bin/sh
# Hibernate a laptop left running with its lid shut.
#
# A closed lid that is still awake is a failed suspend. logind then retries the
# failing operation roughly every 30 seconds, forever, and the machine stays
# fully powered on with the panel lit. Measured on this laptop 2026-11-23:
# 202 failed suspend-then-hibernate attempts between 17:21 and 19:04 drained
# the battery 73% -> 5% with the lid shut the whole time.
#
# This is the backstop, not the primary path. Lid-close is meant to be handled
# by logind (HandleLidSwitch=suspend-then-hibernate); this only fires when that
# did not take the machine down.
set -eu

STATE=/run/presence-guard-hibernate-watchdog
GRACE=600
AC=/sys/class/power_supply/AC/online
BAT=/sys/class/power_supply/BAT0/capacity

[ -r "$AC" ] && [ -r "$BAT" ] || exit 0

on_ac=$(cat "$AC")
capacity=$(cat "$BAT")

hibernate() {
    logger -t presence-guard-watchdog "$1, hibernating"
    rm -f "$STATE"
    exec systemctl hibernate
}

# Last line of defence: a battery this low is hibernated whatever the lid is
# doing, so a stuck machine parks itself instead of dying hard.
if [ "$on_ac" = "0" ] && [ "$capacity" -le 10 ]; then
    hibernate "battery at ${capacity}% on battery"
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

hibernate "lid shut for $(( (now - since) / 60 )) min and still running"
