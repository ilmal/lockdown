"""Fingerprint verification through fprintd."""

from __future__ import annotations

import getpass
import subprocess


class FingerprintError(RuntimeError):
    pass


def available(user: str | None = None) -> bool:
    """True when a fingerprint reader is present (enrollment not required)."""
    user = user or getpass.getuser()
    try:
        out = subprocess.run(
            ["fprintd-list", user], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "Device at" in (out.stdout + out.stderr)


def enrolled_fingers(user: str | None = None) -> list[str]:
    """Fingers with a stored print, e.g. ['right-index', 'left-index']."""
    user = user or getpass.getuser()
    try:
        out = subprocess.run(
            ["fprintd-list", user], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [
        line.strip()[2:] for line in out.stdout.splitlines() if line.strip().startswith("- ")
    ]


def verify(user: str | None = None, timeout: int = 20) -> tuple[bool, str]:
    """Prompt for a finger. Returns (matched, message).

    Blocks until the sensor reads a finger or the timeout expires, so it must
    never be called from the guard loop.
    """
    user = user or getpass.getuser()
    try:
        proc = subprocess.run(
            ["fprintd-verify", user], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "timed out waiting for a finger"
    except (OSError, subprocess.SubprocessError) as exc:
        raise FingerprintError(f"fprintd-verify failed: {exc}") from exc

    blob = (proc.stdout + proc.stderr).lower()
    if proc.returncode == 0 and "verify-match" in blob:
        return True, "fingerprint matched"
    if "verify-no-match" in blob:
        return False, "fingerprint did not match"
    return False, (proc.stderr or proc.stdout or "no result").strip()[:200]
