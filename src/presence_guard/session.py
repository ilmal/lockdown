from __future__ import annotations

import os
import shutil
import subprocess


class SessionError(RuntimeError):
    pass


def _run(cmd: list[str], dry_run: bool) -> tuple[int, str]:
    if dry_run:
        return 0, f"[dry-run] would run: {' '.join(cmd)}"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SessionError(f"{' '.join(cmd)} failed: {exc}") from exc
    return proc.returncode, (proc.stderr or proc.stdout or "").strip()


def session_id() -> str | None:
    return os.environ.get("XDG_SESSION_ID")


def is_locked() -> bool:
    sid = session_id()
    if not sid:
        return False
    code, out = _run(["loginctl", "show", sid, "-p", "LockedHint", "--value"], dry_run=False)
    return code == 0 and out.strip().lower() == "yes"


def lock(dry_run: bool = False) -> str:
    sid = session_id()
    if sid:
        code, out = _run(["loginctl", "lock-session", sid], dry_run)
        if code == 0:
            return out or f"locked session {sid}"
    code, out = _run(["loginctl", "lock-sessions"], dry_run)
    if code == 0:
        return out or "locked all sessions"
    if shutil.which("gdbus"):
        code, out = _run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.ScreenSaver",
                "--object-path",
                "/org/gnome/ScreenSaver",
                "--method",
                "org.gnome.ScreenSaver.Lock",
            ],
            dry_run,
        )
        if code == 0:
            return out or "locked via GNOME ScreenSaver"
    raise SessionError("could not lock the session")


def poweroff(dry_run: bool = False) -> str:
    code, out = _run(["loginctl", "poweroff"], dry_run)
    if code == 0:
        return out or "poweroff requested"
    code, out = _run(["systemctl", "poweroff"], dry_run)
    if code == 0:
        return out or "poweroff requested via systemctl"
    raise SessionError(
        "poweroff denied; see docs/remote-kill.md for the polkit rule or sudoers entry"
    )


def _swap_total_bytes() -> int:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("SwapTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return 0
    return 0


def _mem_total_bytes() -> int:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return 0
    return 0


def _read_resume() -> str:
    try:
        return open("/sys/power/resume").read().strip()
    except OSError:
        return ""


def hibernate_preflight() -> list[str]:
    """Return the reasons hibernation would not work, newest first."""
    problems = []
    try:
        states = open("/sys/power/state").read().split()
    except OSError:
        states = []
    if "disk" not in states:
        problems.append("kernel does not advertise 'disk' in /sys/power/state")

    mem, swap = _mem_total_bytes(), _swap_total_bytes()
    if swap < mem:
        problems.append(
            f"swap is {swap / 2**30:.1f} GiB but RAM is {mem / 2**30:.1f} GiB; "
            "hibernation needs a swap area at least as large as RAM"
        )

    if _read_resume() in ("", "0:0"):
        problems.append(
            "no resume device is configured; the kernel would not know where "
            "to read the image from on boot"
        )
    return problems


def hibernate(dry_run: bool = False) -> str:
    problems = hibernate_preflight()
    if problems:
        raise SessionError(
            "hibernation is not usable on this machine:\n  - "
            + "\n  - ".join(problems)
            + "\nSee docs/hibernate.md."
        )
    code, out = _run(["systemctl", "hibernate"], dry_run)
    if code == 0:
        return out or "hibernate requested"
    raise SessionError("hibernate was refused; see docs/hibernate.md")
