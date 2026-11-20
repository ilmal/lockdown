from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

from . import session

# The failure count is read from the journal rather than from pam_faillock.
# pam_faillock would need the whole PAM stack edited, and a mistake there locks
# you out of sudo and the login screen at once. Log lines are emitted by
# pam_unix for every password prompt, so watching them leaves PAM untouched.
_AUTH_LINE = re.compile(r"pam_unix\((?P<service>[^:)]+):auth\)")
_SESSION_LINE = re.compile(r"pam_unix\((?P<service>[^:)]+):session\): session opened for user (?P<user>[^ (]+)")
_FAILURE_USER = re.compile(r"(?<![A-Za-z])user=(?P<user>[^ =]+)(?![\w=])")
_BY_USER = re.compile(r" by (?P<by>[^ (]+)\(uid=")

# Session-opening lines are attributed to the account that supplied the
# password, which is the "by" field for sudo/su. cron also opens a session for
# nils every 15 minutes; it is excluded by name so it can never reset a count.
DEFAULT_SERVICES = ("gdm-password", "login", "sshd", "sudo")


@dataclass
class Tracker:
    threshold: int = 3
    window_seconds: int = 600
    _failures: dict[str, list[float]] = field(default_factory=dict)

    def _prune(self, user: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        recent = [t for t in self._failures.get(user, []) if t >= cutoff]
        if recent:
            self._failures[user] = recent
        else:
            self._failures.pop(user, None)
        return recent

    def record_failure(self, user: str, now: float) -> int:
        recent = self._prune(user, now)
        recent.append(now)
        self._failures[user] = recent
        return len(recent)

    def record_success(self, user: str) -> None:
        self._failures.pop(user, None)


def classify(message: str, services: tuple[str, ...] = DEFAULT_SERVICES) -> tuple[str, str] | None:
    """Map one journal message to ("failure"|"success", user), or None."""
    session_line = _SESSION_LINE.search(message)
    if session_line and session_line.group("service") in services:
        by_user = _BY_USER.search(message)
        return ("success", by_user.group("by") if by_user else session_line.group("user"))

    auth_line = _AUTH_LINE.search(message)
    if not auth_line or auth_line.group("service") not in services:
        return None

    # Only the "authentication failure" line is counted. A single failed attempt
    # also emits "auth could not identify password" from the PAM conversation
    # retry, which must not count twice.
    if "authentication failure" not in message:
        return None

    failed = _FAILURE_USER.search(message)
    if failed:
        return ("failure", failed.group("user"))

    return None


def _hibernate() -> None:
    try:
        session.lock()
    except session.SessionError as exc:
        print(f"[authwatch] lock failed: {exc}", file=sys.stderr, flush=True)
    try:
        session.hibernate()
        print("[authwatch] hibernated after repeated failed logins", flush=True)
    except session.SessionError as exc:
        print(f"[authwatch] hibernate failed: {exc}", file=sys.stderr, flush=True)


def watch(
    threshold: int = 3,
    window_seconds: int = 600,
    services: tuple[str, ...] = DEFAULT_SERVICES,
    dry_run: bool = False,
) -> None:
    tracker = Tracker(threshold=threshold, window_seconds=window_seconds)
    print(
        f"[authwatch] threshold={threshold} window={window_seconds}s "
        f"services={','.join(services)}",
        flush=True,
    )

    proc = subprocess.Popen(
        ["journalctl", "--follow", "--output=json", "--no-pager", "--lines=0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:
        raise session.SessionError("journalctl produced no output stream")

    try:
        for raw in proc.stdout:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message = entry.get("MESSAGE")
            if not isinstance(message, str):
                continue

            event = classify(message, services)
            if event is None:
                continue
            kind, user = event

            if kind == "success":
                tracker.record_success(user)
                continue

            count = tracker.record_failure(user, time.time())
            print(f"[authwatch] failed login for {user}: {count}/{threshold}", flush=True)
            if count < threshold:
                continue

            tracker.record_success(user)
            if dry_run:
                print("[authwatch] dry-run: would lock and hibernate", flush=True)
                continue
            _hibernate()
            return
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
