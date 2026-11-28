#!/bin/sh
# Put the laptop back to sleep when nothing else will.
#
# Backstop, not the primary path. Lid close is handled by logind
# (HandleLidSwitch=suspend) and idle suspend by GNOME; both work. This covers
# the ways they fail on this machine:
#
#   1. A spurious wake leaves it running with the lid shut. Measured
#      2026-11-27: suspended correctly at 18:41, woke at 03:58, then sat fully
#      awake for 75 min at ~21 W with the panel lit, draining 43% -> 10%.
#
#   2. That same wake also delivered a bogus "lid opened" event, so the lid
#      state cannot be trusted as the sole trigger.
#
#   3. GNOME's sleep-inactive-* policy never fires while any app holds an idle
#      inhibitor. VLC holds one ("Playing some media.") for as long as it is
#      open, which pinned this laptop awake through the whole 2026-11-27 night.
#
# So there are two independent triggers, either of which is enough:
#
#   - the lid has been shut for GRACE seconds (read from /proc/acpi/button/lid,
#     polled from the EC, not from the event stream that goes missing), or
#   - the machine is on battery, has gone IDLE_LIMIT seconds without input, and
#     nothing is actually playing sound.
#
# A oneshot timer only runs while the system is awake, so reaching the end of
# this script already proves the machine stayed up for a whole interval.
#
# Exemptions mirror logind's own docked rule:
#   - an external display attached -> a shut lid is not a sleep request
#   - a blocking sleep inhibitor   -> an app has explicitly forbidden sleep
#   - audio actually playing        -> the user is watching or listening
set -eu

STATE=/run/presence-guard-watchdog-since
GRACE=600       # seconds a shut lid must persist before acting
STALE=2400      # a stamp older than this means we slept; restart the clock
BAT_FLOOR=10    # percent: at or below this, power off no matter what
IDLE_LIMIT=2100 # input-idle seconds before forced suspend on battery (matches
                # sleep-inactive-battery-timeout, so we only act if GNOME did not)
LID=/proc/acpi/button/lid/LID0/state
AC=/sys/class/power_supply/AC/online
BAT=/sys/class/power_supply/BAT0/capacity

log() { logger -t presence-guard-watchdog "$*"; }

[ -r "$AC" ] && [ -r "$BAT" ] || exit 0
on_ac=$(cat "$AC")
capacity=$(cat "$BAT")

# Hard floor, before anything else: at this charge the only safe action is a
# clean power-off. Hibernate is not an option on this laptop — it never
# completes, hanging at ~5 W while looking asleep, draining the pack.
if [ "$on_ac" = "0" ] && [ "$capacity" -le "$BAT_FLOOR" ]; then
    log "battery at ${capacity}% on battery, powering off"
    rm -f "$STATE"
    exec systemctl poweroff
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

uid=$(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $2}' | head -1)
user=$(id -un "${uid:-0}" 2>/dev/null || true)
as_user() { runuser -u "$user" -- env XDG_RUNTIME_DIR="/run/user/$uid" "$@"; }

# Audio actually playing: the user is watching or listening, so leave it alone.
# Only an ACTIVE playback stream counts; a paused or merely open player must not
# hold the machine awake, which is exactly how VLC pinned it on 2026-11-27.
if [ -n "${uid:-}" ] && [ -n "$user" ] && [ -S "/run/user/$uid/bus" ]; then
    if as_user wpctl status 2>/dev/null | grep -qE 'output_[A-Z]+ *> .*\[active\]'; then
        exit 0
    fi
fi

suspend() {
    log "$1, suspending"
    rm -f "$STATE"
    exec systemctl suspend
}

now=$(date +%s)

if [ -r "$LID" ] && [ "$(awk '{print $2}' "$LID")" = "closed" ]; then
    since=0
    [ -f "$STATE" ] && since=$(cat "$STATE")
    # A stamp older than STALE means the machine slept in between (the timer
    # does not run while suspended): a fresh wake, not a long idle run.
    if [ "$since" -eq 0 ] || [ $((now - since)) -ge "$STALE" ]; then
        echo "$now" > "$STATE"
        exit 0
    fi
    [ $((now - since)) -ge "$GRACE" ] || exit 0
    suspend "lid shut for $(( (now - since) / 60 )) min and still running"
fi

rm -f "$STATE"

# Lid state is unreliable here, so also act on plain input idleness on battery.
[ "$on_ac" = "0" ] || exit 0
idle_ms=$(as_user gdbus call --session --dest org.gnome.Mutter.IdleMonitor \
    --object-path /org/gnome/Mutter/IdleMonitor/Core \
    --method org.gnome.Mutter.IdleMonitor.GetIdletime 2>/dev/null | tr -dc '0-9')
[ -n "$idle_ms" ] || exit 0
[ "$idle_ms" -ge $((IDLE_LIMIT * 1000)) ] || exit 0

suspend "no input for $(( idle_ms / 1000 / 60 )) min on battery"
