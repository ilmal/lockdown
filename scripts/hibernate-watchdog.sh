#!/bin/sh
# Put a lid-shut laptop back to sleep when nothing else will.
#
# This is a backstop, not the primary path. Lid close is handled by logind
# (HandleLidSwitch=suspend), which works. This covers three ways that fails:
#
#   1. The machine wakes with the lid still shut and stays awake. Measured
#      2026-11-27: it suspended correctly at 18:41, a spurious wake fired at
#      03:58, and it then sat fully awake for 75 min at ~21 W with the panel lit
#      and the lid closed, draining 43% -> 10%.
#
#   2. logind misses the lid event. The EC on this laptop also logs "The lid
#      device is not compliant to SW_LID"; a missed close means nothing is ever
#      suspended.
#
#   3. GNOME blanks and suspends on idle exactly as the user configured, so if
#      the lid is shut and the machine is still up, that policy has not fired
#      either — which is what a held idle inhibitor looks like.
#
# All three are detected the same way: read the lid from /proc/acpi/button/lid,
# which is polled from the EC and does not depend on the event stream that gets
# lost, and require it to stay shut across several ticks. A oneshot unit only
# runs while the system is awake, so reaching the end of this script already
# proves the machine stayed up for a whole interval.
#
# Exemptions mirror logind's own docked rule:
#   - an external display attached -> a shut lid is not a sleep request
#   - a blocking sleep inhibitor   -> an app has explicitly forbidden sleep
#   - audio actually playing        -> the user is watching or listening
set -eu

STATE=/run/presence-guard-watchdog-since
GRACE=600      # seconds a shut lid must persist before acting
STALE=2400     # a stamp older than this means we slept; restart the clock
BAT_FLOOR=10   # percent: at or below this, power off no matter what
LID=/proc/acpi/button/lid/LID0/state
AC=/sys/class/power_supply/AC/online
BAT=/sys/class/power_supply/BAT0/capacity

log() { logger -t presence-guard-watchdog "$*"; }

[ -r "$AC" ] && [ -r "$BAT" ] || exit 0
on_ac=$(cat "$AC")
capacity=$(cat "$BAT")

# Hard floor, before anything else: at this charge the only safe action is a
# clean power-off. Hibernate is not an option on this laptop — it never
# completes, hanging at ~5 W and draining the pack while looking asleep.
if [ "$on_ac" = "0" ] && [ "$capacity" -le "$BAT_FLOOR" ]; then
    log "battery at ${capacity}% on battery, powering off"
    rm -f "$STATE"
    exec systemctl poweroff
fi

if [ ! -r "$LID" ] || [ "$(awk '{print $2}' "$LID")" != "closed" ]; then
    rm -f "$STATE"
    exit 0
fi

# Docked: an external display means a shut lid is not a request to sleep.
for status in /sys/class/drm/card*-*/status; do
    [ -r "$status" ] || continue
    case "$status" in *eDP*) continue ;; esac
    [ "$(cat "$status")" = "connected" ] && exit 0
done

# An app holds a blocking sleep inhibitor (call, presentation, explicit).
if systemd-inhibit --list --mode=block --no-legend 2>/dev/null | grep -q ' sleep '; then
    exit 0
fi

# Audio playing: the user is watching or listening, so leave the machine alone.
# Only an ACTIVE playback stream counts — a paused or merely-open player must not
# keep the machine awake, which is exactly how VLC (holding an idle inhibitor
# for as long as it is open, with "Playing some media." as its stated reason)
# pinned this laptop awake through a whole night on 2026-11-27.
uid=$(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $2}' | head -1)
if [ -n "${uid:-}" ] && [ -S "/run/user/$uid/bus" ]; then
    user=$(id -un "$uid" 2>/dev/null || true)
    if [ -n "$user" ] && runuser -u "$user" -- env \
            XDG_RUNTIME_DIR="/run/user/$uid" wpctl status 2>/dev/null \
            | grep -qE 'output_[A-Z]+ *> .*\[active\]'; then
        exit 0
    fi
fi

now=$(date +%s)
since=0
[ -f "$STATE" ] && since=$(cat "$STATE")

# A stamp older than STALE means the machine slept in between (the timer does
# not run while suspended), so this is a fresh wake rather than a long idle run.
if [ "$since" -eq 0 ] || [ $((now - since)) -ge "$STALE" ]; then
    echo "$now" > "$STATE"
    exit 0
fi

[ $((now - since)) -ge "$GRACE" ] || exit 0

log "lid shut for $(( (now - since) / 60 )) min and still running, suspending"
rm -f "$STATE"
exec systemctl suspend
