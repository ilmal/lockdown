"""Fingerprint verification that accepts ANY enrolled finger.

`fprintd-verify` does not do this. With no `-f` argument it selects the *first*
enrolled finger and verifies only against that one: with right-index and
right-little enrolled, a scan printed `Verifying: right-index-finger` and never
advanced, so the second finger could never authenticate.

fprintd's D-Bus API supports the right mode — `VerifyStart("any")` is accepted,
the device emits `VerifyFingerSelected` for whichever enrolled finger was
presented, then `VerifyStatus`.

Uses jeepney (pure Python): dbus-python needs a C build and system headers,
which makes the package painful to install in a venv.
"""

from __future__ import annotations

import getpass
import subprocess
import time

from jeepney import DBusAddress, HeaderFields, MatchRule, new_method_call, message_bus
from jeepney.io.blocking import open_dbus_connection

DBUS_NAME = "net.reactivated.Fprint"
DEVICE_PATH = "/net/reactivated/Fprint/Device/0"
IFACE = "net.reactivated.Fprint.Device"

DEVICE = DBusAddress(DEVICE_PATH, bus_name=DBUS_NAME, interface=IFACE)
_MATCH_DONE = ("verify-match", "verify-no-match")


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


def _call(conn, method: str, signature: str = "", body: tuple = ()):
    msg = new_method_call(DEVICE, method, signature=signature, body=body)
    return conn.send_and_get_reply(msg)


def verify_any(
    user: str | None = None, timeout: int = 20, verbose: bool = False
) -> tuple[bool, str]:
    """Verify against ANY enrolled finger. Returns (matched, message)."""
    user = user or getpass.getuser()
    try:
        conn = open_dbus_connection(bus="SYSTEM")
    except Exception as exc:
        raise FingerprintError(f"cannot connect to the system bus: {exc}") from exc

    try:
        _call(conn, "Claim", "s", (user,))

        rule = MatchRule(type="signal", interface=IFACE, path=DEVICE_PATH)
        signals = conn.filter(rule, bufsize=50)

        _call(conn, "VerifyStart", "s", ("any",))
        state = {"matched": False, "message": "no result", "done": False, "finger": None}
        deadline = time.monotonic() + timeout
        while not state["done"] and time.monotonic() < deadline:
            try:
                msg = signals.get(timeout=max(0.05, deadline - time.monotonic()))
            except Exception:
                continue
            member = msg.header.fields.get(HeaderFields.member)
            body = msg.body
            if member == "VerifyFingerSelected" and body:
                state["finger"] = str(body[0])
                if verbose:
                    print(f"  scanning against {state['finger']}", flush=True)
            elif member == "VerifyStatus" and body:
                result = str(body[0])
                state["message"] = result
                if result in _MATCH_DONE:
                    state["matched"] = result == "verify-match"
                    state["done"] = True
                elif verbose:
                    print(f"  {result}", flush=True)

        if not state["done"]:
            return False, "timed out waiting for a finger"
        label = f" ({state['finger']})" if state["finger"] else ""
        return state["matched"], f"{'matched' if state['matched'] else 'did not match'}{label}"
    finally:
        for method in ("VerifyStop", "Release"):
            try:
                _call(conn, method)
            except Exception:
                pass
        conn.close()


def verify(user: str | None = None, timeout: int = 20) -> tuple[bool, str]:
    """Backwards-compatible alias: always any-finger."""
    return verify_any(user, timeout=timeout)
