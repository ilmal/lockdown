# Idle and lid-close hibernate

Two separate timers, because a lid and an idle machine reach the 35-minute mark
differently.

## Lid closed → suspend, then hibernate after 35 min

`config/systemd/logind.conf.d/10-lockdown.conf`:

```ini
[Login]
HandleLidSwitch=suspend-then-hibernate
HandleLidSwitchExternalPower=suspend-then-hibernate
HandleLidSwitchDocked=ignore
```

Suspend resumes instantly if you come back within the half hour; after 35
minutes systemd wakes itself from a `CLOCK_BOOTTIME_ALARM` timer and hibernates.
An overnight-closed laptop therefore finishes powered off with the LUKS key
gone, instead of sitting in `s2idle` burning the battery — which is what it has
been doing: every suspend in the journal is `PM: suspend entry (s2idle)` with
no `PM: hibernation` entry anywhere.

The 35 minutes lives in `sleep.conf.d/10-lockdown.conf` as `HibernateDelaySec`.
It must be set explicitly: unset, systemd waits for an ACPI low-battery alarm
instead of a fixed delay.

**GNOME 50 does not implement the lid action itself.** `gsd-power` only plays a
sound and locks the screen when suspend is inhibited; it leaves the switch to
logind. `lid-close-ac-action`/`lid-close-battery-action` are ignored, and the
enum has no `suspend-then-hibernate` value anyway. `HandleLidSwitchDocked=ignore`
covers the case where GNOME holds its temporary `handle-lid-switch` inhibitor
because an external monitor is attached.

## Idle 35 min → hibernate

Here GNOME's timer is the right one, which is why the idle policy is a
gsettings key and not logind's `IdleActionSec`:

- GNOME measures *last input*, so 35 minutes of no keyboard or mouse is 35
  minutes.
- logind's `IdleActionSec` only starts counting once the session reports itself
  idle, which happens at screen blank — 10 minutes later at the current
  `idle-delay` of 600 s.

```bash
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'hibernate'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'hibernate'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 2100
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 2100
```

These previously read `'suspend'` / 1800 s (AC) and 1500 s (battery). Hibernate
was not reachable from the GUI before because `CanHibernate` answered `"no"`,
so the option did not appear; the polkit rule from
[`hibernate.md`](hibernate.md) fixes that too.
