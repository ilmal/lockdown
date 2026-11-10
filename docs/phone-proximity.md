# Phone proximity

The goal: "my phone is near the laptop" counts as one factor.

## What an iPhone exposes

Verified on this machine 2026-11-10 with an iPhone 17 Pro Max:

| Signal | Available? | Measures distance? |
|---|---|---|
| BLE advertising RSSI | **yes** — Apple manufacturer data (`0x004c`), ~-45 dBm on a desk | yes, coarsely |
| BLE address | rotates every ~15 min | — |
| Classic Bluetooth RSSI | only while connected | no |
| Tailscale ping | yes, 30 ms direct | **no — useless here** |

Tailscale is deliberately **not** used. It answers "is this phone on the
internet", which tells you nothing about whether it is on the desk. A phone
left at home on wifi still pings. It was in an early version of the demo and
was removed for being noise.

## Can we hold a steady connection instead of scanning?

Tested, and no. Attempts on 2026-11-10:

1. **Connect to the current advertiser** — `bluetoothctl connect` reports
   "Connection successful", and three seconds later the device is
   `Connected: no`. iOS drops any LE link that is not driven by an app, so the
   connection cannot be held.
2. **Classic Bluetooth RSSI** (`hcitool rssi`) — returns "Not connected", and an
   iPhone does not stay connected to a laptop for this purpose.
3. **Pin the address** — the address rotated mid-session from
   `68:25:55:9B:40:91` to `4B:A8:49:42:02:72` and `57:BF:BC:96:78:09` within
   the same hour. There is nothing stable to pin.

So scanning advertisements is the only workable local signal. A stable
per-phone identity would require an app on the phone advertising a fixed
identifier, or the phone doing an active Wi-Fi RTT exchange — neither exists
without writing an iOS app.

### The MAC address changes

An iPhone rotates its Bluetooth address constantly and does not advertise a
pinnable name. So this cannot ask "is *my* phone near"; it asks "is *an Apple
device* near". In a room with three iPhones that is not proof of anything on its
own — which is exactly why phone proximity is one of *three* secondary factors
and never sufficient alone.

### Strongest advertiser wins

A neighbour's phone across the room registers around -73 dBm while yours is
around -45. Averaging them is wrong, so the engine takes the strongest sample
in each burst.

## Distance is a band, not a measurement

RSSI is converted with the log-distance path loss model:

```
d = 10 ** ((tx_power - rssi) / (10 * n))
```

with `tx_power = -59 dBm` (1 m reference) and `n = 2.0`. Indoors, walls and the
laptop's own body block signal, so the number is optimistic. Treat it as
"close / nearby / far", not as metres you can trust.

## Smoothing and hysteresis

Raw BLE RSSI swings 10–20 dB between packets. The engine takes the maximum of
each scan, then the median across a rolling window of six.

State changes use hysteresis: enter **near** at ≤ 2.5 m, leave only at
≥ 6 m. Without that, a distance sitting on the boundary flaps every scan and
would make the factor useless for authentication.

## Limits worth stating

- Wi-Fi/BT interference and a lid-closed laptop change the numbers; recalibrate
  with the demo app in the room you actually use.
- Any nearby Apple device satisfies the factor. Combine it with fingerprint or
  face, as the policy does.
- Scanning is not free: `bluetoothctl scan on` costs ~4 s of radio activity. The
  demo polls once per second; a real policy check should poll far less often.

## Try it

```bash
presence-guard demo          # watch distance update live
```

Move the phone away and watch the state flip at the thresholds.

## Do you need to write an iOS app? The options, ranked

Short answer: **no app is required for a usable result**, but nothing short of an
app or a dedicated beacon gives you *stable identity*.

| Option | Effort | Stable identity? | Distance? | Notes |
|---|---|---|---|---|
| **BLE beacon** (AirTag, Tile, cheap iBeacon) | Buy it (~300 kr) | **Yes** — fixed MAC | Yes, RSSI | Best effort/result ratio. Keep it on your keys or in your bag. |
| **iOS Shortcut + periodic HTTP hit** | 10 min | Yes (it's your phone) | **No** — only "online" | Useless for proximity; listed because it's what people try first. |
| **Own iOS app** (CoreLocation iBeacon ranging) | Days | **Yes** | **Yes, accurate** | The only phone-native way to get true ranging. Needs Xcode + a dev account for sideloading, re-sign every 7 days unless you pay. |
| **Own iOS app** (BLE peripheral advertising a fixed UUID) | Days | **Yes** | Yes, coarse | Simpler than ranging; the laptop scans for that UUID. App must be foregrounded or use background modes. |
| **Current heuristic** (any Apple advertiser) | Done | **No** | Coarse | Fine only because phone is one of three factors. |
| Wi-Fi RTT (802.11mc) | — | — | — | iPhone does not expose this to third parties. Not an option. |
| Find My / iCloud | — | — | — | No local API, cloud round-trip; not proximity. |

### Why a beacon wins for your demo

An iBeacon advertises a **fixed UUID/major/minor** and a **fixed address**, so the
laptop can tell "your beacon" from "some iPhone nearby" and can log real,
repeatable distances. That turns the phone factor from a heuristic into something
you can actually defend in a demo, for the price of a keyring tag.

### If you do write the app

The least-work version is **not** ranging — it is a BLE peripheral that
advertises one fixed service UUID, plus a laptop-side scan for that UUID. Ranging
with `CLBeaconRegion` gives real metres but needs location permission and a
background mode, and iOS throttles background ranging heavily.

## Bluetooth only, no hotspot, no beacon: what is actually left

Measured 2026-11-10 on this laptop with an iPhone 17 Pro Max. Every row is a test
result, not a guess.

| Approach | Result |
|---|---|
| Bond/pair the iPhone for a stable IRK | **Fails** — `bluetoothctl pair <mac>` → `org.bluez.Error.ConnectionAttemptFailed`. iOS will not bond with an unpaired Linux host. |
| Hold a BLE connection | **Fails** — connect reports success, `Connected: no` within 3 s. iOS drops undriven LE links. |
| Pin the BLE address | **Impossible** — rotates. Observed in one session: `68:25:55:9B:40:91` → `62:A7:27:E0:F4:43` → `48:9C:F8:CA:FA:E6` → `7B:F9:F9:65:5D:87`. |
| Classic BT RSSI (`hcitool rssi`) | **Unavailable** — requires a connection, which iOS will not hold. |
| Stable identity from the advertisement | **No** — the payloads are Continuity (`0x10` Nearby, `0x0c` Handoff, `0x01` AirDrop), all carrying rotating identifiers. |
| mDNS / Bonjour hostname | **No** — no `.local` records from the phone on this network in a 20 s multicast sniff. |
| **Signal strength of Apple advertisers (BLE RSSI)** | **Works** — this is all that is left. |

### What the BLE fallback can and cannot do

It measures **an Apple device's** distance, not your phone's identity. In a room
with one iPhone that is a reasonable proxy; with several it is not proof of
anything.

That is acceptable only because phone is one of three secondary factors and the
policy needs two. It is not acceptable as a sole factor, and it should never be
described as "proximity to my phone".

### The honest conclusion

With no hotspot, no beacon, and no iOS app, **Bluetooth cannot identify your
phone** — only "some Apple device is at this distance". If that is not good
enough, the remaining options are an app (iOS peripheral advertising a fixed
UUID; needs Xcode, and there is no macOS in this fleet) or a beacon (rejected).

## You do NOT need to build your own app

Earlier versions of this document said an app was required. That was wrong: the
right way is not a custom app that advertises a raw service UUID — it is an
**existing beacon-broadcaster app** turning the iPhone into an iBeacon.

The key difference is which API does the advertising:

| Route | Survives backgrounding? | Stable identity? |
|---|---|---|
| Generic `CBPeripheralManager.startAdvertising(serviceUUIDs:)` | **No** — iOS strips the payload to a nameless overflow packet that wildcard scanners cannot see, and never restores it after termination | no |
| **iBeacon via `CLBeaconRegion.peripheralData(withMeasuredPower:)`** | Much better — iBeacon frames are a system-recognised format, and apps can be relaunched by CoreLocation region monitoring | **yes**, the UUID is fixed |

### What to install

Any of these can make an iPhone transmit a configurable iBeacon UUID:

- **Locate Beacon** (App Store, Radius Networks) — has a "Transmit" mode with
  configurable UUID/major/minor.
- **nRF Connect** (Nordic Semiconductor) — has a "Beacon / iBeacon" advertiser.
- **Beacon Simulator** and similar — same idea.

Set a UUID you generate yourself, keep the app running, and point the config at
that UUID:

```toml
[phone]
mode = "ibeacon"
hotspot_ssid = "your-uuid-here"
```

The laptop then scans for `02 15 <uuid>` inside Apple manufacturer data, which is
what `scan_ibeacon()` implements. The MAC keeps rotating; the UUID does not, so
identity is stable.

### Honest limits

- **The app must be running and the phone awake.** iOS does suspend third-party
  apps eventually, and after a force-quit nothing advertises. CoreLocation region
  monitoring can relaunch the app for a short window, but this is not a
  guaranteed-forever background service.
- **Battery:** far cheaper than a Personal Hotspot, but non-zero.
- Treat it as "phone present" for a demo, not as a cryptographic authenticator.
  Anyone who learns the UUID can spoof the advertisement; iBeacon has no
  challenge-response. The policy requiring two of three factors is what makes
  that acceptable.
