"""Fingerprint verification that accepts ANY enrolled finger.

`fprintd-verify` with no `-f` selects the *first* enrolled finger and only ever
verifies against that one. Confirmed on this machine: with right-index and
right-little enrolled, the scan printed `Verifying: right-index-finger` and never
advanced, so the second finger could never authenticate.

libfprint's D-Bus API does have an `any` mode, and `VerifyStart("any")` is
accepted — but the daemon emits no `VerifyStatus`/`VerifyFingerSelected` signals
to a client connection here, so that route cannot be verified and is not relied
on.

What works is running the CLI once per enrolled finger and accepting if any of
them matches. Each attempt gets a short window, and the first match wins. The
cost is one prompt per finger on a miss; on the common path (first finger
matches) it costs exactly what the CLI costs.
"""

from __future__ import annotations

import getpass
import subprocess

# Seconds to wait for a touch on each finger. Long enough to place a finger,
# short enough that walking through five fingers does not feel broken.
ATTEMPT_TIMEOUT = 8


class FingerprintError(RuntimeError):
    pass


def available(user: str | None = None) -> bool:
    user = user or getpass.getuser()
    try:
        out = subprocess.run(
            ["fprintd-list", user], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "Device at" in (out.stdout + out.stderr)


def enrolled_fingers(user: str | None = None) -> list[str]:
    """Enrolled finger names, e.g. ['right-index-finger', 'right-little-finger']."""
    user = user or getpass.getuser()
    try:
        out = subprocess.run(
            ["fprintd-list", user], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return []
    fingers = []
    for line in out.stdout.splitlines():
        line = line.strip()
        # Lines look like " - #0: right-index-finger"
        if line.startswith("- "):
            name = line[2:].strip()
            if ":" in name:
                name = name.split(":", 1)[1].strip()
            fingers.append(name)
    return fingers


def _verify_one(user: str, finger: str, timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["fprintd-verify", "-f", finger, user],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except (OSError, subprocess.SubprocessError) as exc:
        raise FingerprintError(f"fprintd-verify failed: {exc}") from exc

    blob = (proc.stdout + proc.stderr).lower()
    if "verify-match" in blob:
        return True, "matched"
    if "verify-no-match" in blob:
        return False, "no match"
    return False, "timeout"


def verify_any(
    user: str | None = None,
    timeout: int = ATTEMPT_TIMEOUT,
    verbose: bool = False,
) -> tuple[bool, str]:
    """Accept a scan from ANY enrolled finger.

    Tries each enrolled finger in turn and returns on the first match. Returns
    (False, ...) when every finger either failed to match or timed out.
    """
    user = user or getpass.getuser()
    fingers = enrolled_fingers(user)
    if not fingers:
        raise FingerprintError(f"no fingerprints enrolled for {user}")

    for finger in fingers:
        if verbose:
            print(f"  trying {finger}…", flush=True)
        matched, reason = _verify_one(user, finger, timeout)
        if matched:
            return True, f"matched ({finger})"
        if verbose:
            print(f"    {reason}", flush=True)
    return False, "no enrolled finger matched"


def verify(user: str | None = None, timeout: int = ATTEMPT_TIMEOUT) -> tuple[bool, str]:
    """Backwards-compatible alias: always any-finger."""
    return verify_any(user, timeout=timeout)
