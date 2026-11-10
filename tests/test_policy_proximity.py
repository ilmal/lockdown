from __future__ import annotations

import statistics

import pytest

from presence_guard.policy import FactorState, Policy
from presence_guard.proximity import ProximityEngine, rssi_to_meters


def test_policy_needs_password_plus_two():
    p = Policy()
    assert p.evaluate(FactorState(password=True))["satisfied"] is False
    assert p.evaluate(FactorState(password=True, phone=True))["satisfied"] is False
    assert (
        p.evaluate(FactorState(password=True, phone=True, fingerprint=True))["satisfied"]
        is True
    )


@pytest.mark.parametrize(
    "combo",
    [
        {"phone": True, "fingerprint": True},
        {"phone": True, "face": True},
        {"fingerprint": True, "face": True},
        {"phone": True, "fingerprint": True, "face": True},
    ],
)
def test_all_two_of_three_combinations_unlock(combo):
    state = FactorState(password=True, **combo)
    assert Policy().evaluate(state)["satisfied"] is True


def test_missing_password_blocks_even_with_every_factor():
    state = FactorState(password=False, phone=True, fingerprint=True, face=True)
    result = Policy().evaluate(state)
    assert result["satisfied"] is False
    assert result["missing_password"] is True


def test_matrix_lists_only_qualifying_combinations():
    matrix = Policy().matrix()
    assert "password + phone + fingerprint" in matrix
    assert all(m.count("+") >= 2 for m in matrix)


def test_rssi_to_meters_is_monotonic():
    values = [rssi_to_meters(r) for r in (-40, -50, -60, -70, -80)]
    assert values == sorted(values)


def test_rssi_reference_point_is_one_metre():
    assert abs(rssi_to_meters(-59.0) - 1.0) < 0.001


def test_engine_uses_the_strongest_advertiser(monkeypatch):
    # A neighbour's phone at -73 must not drag your phone at -45 away.
    monkeypatch.setattr(
        "presence_guard.proximity.scan_apple_rssi", lambda *_a, **_k: [-73.0, -45.0]
    )
    engine = ProximityEngine(near_m=2.5, far_m=6.0)
    reading = engine.poll()
    assert reading is not None
    assert reading.meters < 1.0
    assert engine.near is True


def test_engine_reports_error_without_samples(monkeypatch):
    monkeypatch.setattr(
        "presence_guard.proximity.scan_apple_rssi", lambda *_a, **_k: []
    )
    engine = ProximityEngine()
    assert engine.poll() is None
    assert "no Apple BLE advertiser" in engine.last_error


def test_hysteresis_prevents_flapping(monkeypatch):
    """Once near, a reading between the bounds must not flip the state."""
    engine = ProximityEngine(near_m=2.5, far_m=6.0, window=1)
    # -72 dBm ~= 4.5 m: between near and far, so state should persist.
    monkeypatch.setattr(
        "presence_guard.proximity.scan_apple_rssi", lambda *_a, **_k: [-45.0]
    )
    assert engine.poll() is not None and engine.near is True

    monkeypatch.setattr(
        "presence_guard.proximity.scan_apple_rssi", lambda *_a, **_k: [-72.0]
    )
    engine.poll()
    assert engine.near is True, "must stay near until past far_m"

    monkeypatch.setattr(
        "presence_guard.proximity.scan_apple_rssi", lambda *_a, **_k: [-85.0]
    )
    engine.poll()
    assert engine.near is False, "past far_m must drop the state"
