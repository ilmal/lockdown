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

## The lid policy was not actually working (fixed 2026-11-25)

Setting `HandleLidSwitch=suspend-then-hibernate` is necessary but was **not
sufficient** on this laptop. Measured from the 2026-11-23 journal: the lid was
shut at 17:20 and logind then attempted `suspend-then-hibernate` **203 times,
failing 202**. The machine stayed fully awake with the panel lit, drew about
30 W, and drained 73% → 5% in under two hours. It then began hibernating at 5%
and the battery died while the kernel was still writing the 10.6 GiB image —
which is why the next boot logged `PM: Image not found (code -22)` and started
fresh instead of resuming.

Every failure was the same line:

```
nvidia 0000:01:00.0: PM: pci_pm_suspend(): nv_pmops_suspend [nvidia] returns -5
PM: Some devices failed to suspend, or early wake event detected
```

### Cause: the NVIDIA hook was not wired into the suspend-then-hibernate path

The NVIDIA driver ships one systemd hook per sleep operation:

| Unit | Pulled in by |
|---|---|
| `nvidia-suspend.service` | `systemd-suspend.service` |
| `nvidia-hibernate.service` | `systemd-hibernate.service` |
| `nvidia-suspend-then-hibernate.service` | `systemd-suspend-then-hibernate.service` |

Only the first two were enabled. `nvidia-suspend-then-hibernate.service` was
**disabled**, so on the `suspend-then-hibernate` path `nvidia-sleep.sh suspend`
never ran and the driver refused the PCI suspend with `-EIO`.

This also explains the shape of the evidence: plain suspend worked fine until
2026-11-20 (`nvidia-suspend.service` ran on every attempt, 0 failures on Nov
16–19), and *every* attempt after the lid policy was switched to
`suspend-then-hibernate` on 2026-11-20 13:36 failed. `journalctl | grep -c
nvidia-suspend-then-hibernate.service` returned **0** — it had never run once.

Fix: `systemctl enable nvidia-suspend-then-hibernate.service`.

### Why "the screen is still on" is the same bug

A failed suspend leaves the machine running, so nothing turns the panel off.
The kernel had already logged

```
ACPI: button: The lid device is not compliant to SW_LID
```

on every attempt. GNOME does not implement lid actions (see above), so it does
not blank the screen on lid close either — the only thing that turns the panel
off is a suspend that succeeds. When the suspend fails, the panel stays lit.
There is therefore no separate "screen stays on" defect to chase: fix the
suspend and the panel goes dark.

### The backstop: `presence-guard-hibernate-watchdog.timer`

Because the primary lid path depends on a third-party driver hook, a timer
(`scripts/hibernate-watchdog.sh`, every 2 minutes) now checks three things:

- a battery at or below 10% on battery power → hibernate immediately;
- lid shut for 10+ minutes while still running → hibernate;
- an attached external display (non-eDP connector `connected`) → do nothing,
  matching `HandleLidSwitchDocked=ignore`.

The timer only fires while the machine is awake, so reaching the end of the
script is itself proof the lid has been shut and the machine stayed up. This
catches both a future driver regression and any other cause of a lid-close that
did not take the machine down.

### The battery safety net also needed fixing

`/etc/UPower/UPower.conf` shipped `CriticalPowerAction=HybridSleep` acting at
2%. On this laptop that is useless: hibernate takes several seconds just to
allocate and write a 10.6 GiB image, and at 2% there is not enough charge left
to finish it — which is exactly how the 2026-11-23 session was lost. The
drop-in `config/UPower/UPower.conf.d/90-critical-battery.conf` sets
`PercentageAction=10.0` and `CriticalPowerAction=Hibernate`.

UPower has no `.conf.d` documented in the package, but `upowerd` contains the
`UPower.conf.d` string and ships `/etc/UPower/UPower.conf.d/README.md`, so
drop-ins are the supported route and avoid editing a dpkg-owned file.

## Update 2026-11-26: hibernation itself is broken — policy is suspend-only

The NVIDIA hook above really was broken and really is fixed: since 2026-11-25
every lid-close suspend has succeeded and the panel goes dark. But it did not
end the drained-battery reports, and the journal from the next drain shows why:

```
10:28:25  PM: hibernation: hibernation entry     <- lid closed 09:53, suspend,
10:28:25  Performing sleep operation 'hibernate'    then hibernate after 35 min
   ...8 hours of silence...
18:29:35  Lid opened / Marking nosave pages /
          Preallocating image memory / hibernation exit
```

Across **all 13 hibernation attempts since 2026-11-16** the kernel has never
logged `PM: hibernation: Saving image data pages` or `Wrote … kbytes` — not
once. It enters hibernation, never finishes writing the image, never powers
off, and sits in a half-frozen state drawing **~5-6 W**. The battery evidence
is unambiguous: the 2026-11-26 attempt drained **77% → 7% in 7.75 h (~9%/h)
while "hibernated"**; the 2026-11-24 → 25 attempt lost 34% over 38 h. A real
S4 draws a fraction of a watt. When the lid is opened the kernel unwinds the
entry path ("hibernation exit"), the session comes back from RAM, and it *looks*
like hibernation worked — which is exactly why this hid for so long.

This firmware's ACPI S4 was already known broken (`platform` mode fails with
"Device or resource busy", which is why `HibernateMode=shutdown` was chosen);
the `shutdown` path hangs too. There is no working hibernate to fall back to.

### Policy is therefore suspend-only

- `HandleLidSwitch=suspend` (both AC and battery), not suspend-then-hibernate.
  s2idle is proven on this laptop: three consecutive 13-15 h nights on Nov
  16-19 with no power loss, and every suspend since 2026-11-25 has succeeded.
- GNOME idle: `sleep-inactive-*-type='suspend'` (was `'hibernate'` — leaving
  that alone would hang the machine after 35 idle minutes).
- UPower: `CriticalPowerAction=PowerOff` at 10%. Hibernate as the critical
  action would hang and drain to death anyway; a clean power-off at 10% beats a
  dead filesystem.
- `presence-guard-hibernate-watchdog.timer`: ≤10% on battery → power-off; lid
  shut 10+ min and still running → retry suspend (it can no longer hibernate,
  because hibernation hangs).

### `presence-guard authwatch` is affected

`authwatch` hibernates after repeated failed logins to kill the in-RAM LUKS
key. With hibernation hanging, the machine black-screens but keeps running with
the key resident — the security property silently disappears. Until
hibernation is fixed, that action should be power-off (also kills the key,
loses the session). Not changed automatically; see
`docs/failed-login-hibernate.md` for the trade-off.

### To actually fix hibernation (needs a test session)

The hang is before the image write — either a device freeze callback
(`dpm_suspend_start(PMSG_FREEZE)`) or the snapshot path. Bisecting it needs one
controlled session with `no_console_suspend` / `pm_test=devices`, i.e. real
hibernate attempts with the console watching. Not safe to run blind.
