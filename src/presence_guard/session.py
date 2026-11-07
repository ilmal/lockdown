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
