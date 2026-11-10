"""Phone proximity as an authentication factor.

Two independent signals, because neither alone is trustworthy:

* **BLE RSSI** — actually measures distance. iPhones rotate their Bluetooth
  address every ~15 minutes, so this cannot pin a MAC. Instead it looks for
  Apple manufacturer data (company id 0x004c) and reports the strongest Apple
  advertiser seen. That is a heuristic: *any* nearby iPhone counts, so it is
  only usable when combined with a stronger factor, which is how the policy
  works.
* **Tailscale presence** — proves the specific device is online, but says
  nothing about distance.

See docs/phone-proximity.md.
"""

from __future__ import annotations

import re
import statistics
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field

APPLE_COMPANY_ID = "0x004c"

# d = 10 ** ((tx_power - rssi) / (10 * n)). tx_power is the reference RSSI at
# 1 m (-59 dBm is the usual Apple default) and n=2.0 assumes free space.
# Indoors this is optimistic, so treat the output as a band, not a measurement.
TX_POWER_1M = -59.0
PATH_LOSS_EXPONENT = 2.0

_RSSI_LINE = re.compile(r"Device ([0-9A-F:]{17}) RSSI: 0x[0-9a-f]+ \((-?\d+)\)")


def rssi_to_meters(
    rssi: float, tx_power: float = TX_POWER_1M, n: float = PATH_LOSS_EXPONENT
) -> float:
    return 10.0 ** ((tx_power - rssi) / (10.0 * n))


@dataclass
class Reading:
    rssi: float
    meters: float
    samples: int
    at: float = field(default_factory=time.time)


def scan_apple_rssi(seconds: float = 4.0) -> list[float]:
    """Collect RSSI of Apple BLE advertisers seen during the scan.

    ManufacturerData and the RSSI line arrive in either order within a scan,
    so track which MACs are Apple and which RSSI each has, then join at the
    end. Attributing by line order alone made this intermittently return
    nothing.
    """
    proc = subprocess.Popen(
        ["bluetoothctl", "--timeout", str(int(seconds) + 1), "scan", "on"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    last_rssi: dict[str, float] = {}
    apple_macs: set[str] = set()
    current: str | None = None
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                break
            m = _RSSI_LINE.search(line)
            if m:
                current = m.group(1)
                last_rssi[current] = float(m.group(2))
                continue
            if APPLE_COMPANY_ID in line and current is not None:
                apple_macs.add(current)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
    return [last_rssi[mac] for mac in apple_macs if mac in last_rssi]


class ProximityEngine:
    """Turns repeated scans into a smoothed distance with hysteresis."""

    def __init__(
        self,
        near_m: float = 2.5,
        far_m: float = 6.0,
        window: int = 6,
        mode: str = "ble",
        hotspot_ssid: str = "",
    ):
        self.near_m = near_m
        self.far_m = far_m
        self.samples: deque[float] = deque(maxlen=window)
        self.near = False
        self.last_reading: Reading | None = None
        self.last_error: str | None = None
        self.mode = mode
        self.hotspot_ssid = hotspot_ssid
        self.last_bssid: str | None = None

    def poll(self) -> Reading | None:
        if self.mode == "hotspot":
            return self._poll_hotspot()
        return self._poll_ble()

    def _poll_hotspot(self) -> Reading | None:
        if not self.hotspot_ssid:
            self.last_error = "phone.hotspot_ssid is not configured"
            return None
        reading = scan_hotspot(self.hotspot_ssid)
        if reading is None:
            # Not visible means out of range OR hotspot off; either way the
            # phone cannot contribute this factor.
            self.last_error = f"hotspot {self.hotspot_ssid!r} not visible"
            self.near = False
            self.samples.clear()
            return None
        self.last_bssid = reading.bssid
        self.samples.append(reading.meters)
        meters = statistics.median(self.samples)
        if meters <= self.near_m:
            self.near = True
        elif meters >= self.far_m:
            self.near = False
        self.last_error = None
        self.last_reading = Reading(
            rssi=(reading.signal / 2.0) - 100.0,
            meters=meters,
            samples=len(self.samples),
        )
        return self.last_reading

    def _poll_ble(self) -> Reading | None:
        values = scan_apple_rssi()
        if not values:
            self.last_error = "no Apple BLE advertiser seen"
            return None
        # Take the STRONGEST advertiser, not the median: a neighbour's iPhone
        # across the room shows up at -73 dBm, and averaging it in would push
        # your phone (around -45) away from the laptop on paper.
        self.samples.append(max(values))
        smoothed = statistics.median(self.samples)
        meters = rssi_to_meters(smoothed)
        # Hysteresis so the state does not flap when distance sits on a boundary.
        if meters <= self.near_m:
            self.near = True
        elif meters >= self.far_m:
            self.near = False
        self.last_error = None
        self.last_reading = Reading(rssi=smoothed, meters=meters, samples=len(self.samples))
        return self.last_reading



# --------------------------------------------------------------------------
# Wi-Fi proximity: identify the phone by its Personal Hotspot SSID.
#
# This is the only local signal that gives STABLE identity with no app and no
# beacon, because the SSID is a name you choose and the iPhone keeps its
# hotspot BSSID stable per device. Signal strength then gives distance the
# same way BLE does.
#
# Requires: Settings > Personal Hotspot > Allow Others to Join = on, and
# "Maximize Compatibility" = on so it advertises 2.4 GHz (a 5 GHz-only hotspot
# is invisible to many adapters and scans far more slowly).
# --------------------------------------------------------------------------


@dataclass
class WifiReading:
    ssid: str
    bssid: str
    signal: int  # 0-100 from NetworkManager
    meters: float
    at: float = field(default_factory=time.time)


def wifi_signal_to_meters(signal_pct: int) -> float:
    """Approximate distance from NetworkManager's 0-100 quality figure.

    NM maps RSSI roughly linearly: 100 ~= -50 dBm, 0 ~= -100 dBm, so
    rssi = signal/2 - 100. Fed through the same path-loss model as BLE.
    """
    rssi = (signal_pct / 2.0) - 100.0
    return rssi_to_meters(rssi)


def scan_hotspot(ssid: str) -> WifiReading | None:
    """Find a specific SSID in a fresh scan. Returns None when not visible."""
    try:
        subprocess.run(["nmcli", "dev", "wifi", "rescan"], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        out = subprocess.run(
            ["nmcli", "-e", "no", "-t", "-f", "SSID,SIGNAL,BSSID", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    best: WifiReading | None = None
    for line in out.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        name = parts[0]
        if name != ssid:
            continue
        try:
            signal = int(parts[1])
        except ValueError:
            continue
        bssid = ":".join(parts[2:])
        reading = WifiReading(
            ssid=name, bssid=bssid, signal=signal, meters=wifi_signal_to_meters(signal)
        )
        if best is None or reading.signal > best.signal:
            best = reading
    return best
