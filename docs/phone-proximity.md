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
