from __future__ import annotations

import numpy as np
import pytest

from presence_guard import camera, config, guard, recognizer


class FakeRec:
    def __init__(self, matches):
        self._matches = list(matches)
        self._i = 0

    def load(self):
        pass

    def predict(self, _face):
        value = self._matches[min(self._i, len(self._matches) - 1)]
        self._i += 1
        return recognizer.Result(matched=value, distance=40.0 if value else 90.0, threshold=62.0, label=0)


def _guard(tmp_path, monkeypatch, matches, **verify):
    monkeypatch.setenv("PRESENCE_GUARD_DATA", str(tmp_path))
    cfg = config.Config()
    for key, value in verify.items():
        setattr(cfg.verify, key, value)

    g = guard.Guard.__new__(guard.Guard)
    g.cfg = cfg
    g.dry_run = True
    g.rec = FakeRec(matches)
    g.absent_since = None
    g.impostor_streak = 0
    g._episode_locked = False
    return g


def _patch_face(monkeypatch, present: bool):
    fake_face = camera.Face((0, 0, 10, 10), np.zeros((100, 100), np.uint8)) if present else None
    monkeypatch.setattr(guard.camera, "grab_frame", lambda *a, **k: np.zeros((360, 640, 3), np.uint8))
    monkeypatch.setattr(guard.camera, "largest_face", lambda *a, **k: fake_face)


def test_match_keeps_guard_quiet(tmp_path, monkeypatch):
    _patch_face(monkeypatch, present=True)
    g = _guard(tmp_path, monkeypatch, [True, True])
    assert g.evaluate_once().state == "present"
    assert g.evaluate_once().state == "present"


def test_impostor_locks_once_per_episode(tmp_path, monkeypatch):
    _patch_face(monkeypatch, present=True)
    g = _guard(tmp_path, monkeypatch, [False, False, False, False], impostor_checks=2)

    first = g.evaluate_once()
    assert first.action is None  # streak 1/2

    second = g.evaluate_once()
    assert second.action == "would-lock"

    third = g.evaluate_once()
    assert third.action is None
    assert "already locked" in third.reason


def test_returning_user_resets_the_episode(tmp_path, monkeypatch):
    _patch_face(monkeypatch, present=True)
    g = _guard(tmp_path, monkeypatch, [False, False, True, False, False], impostor_checks=2)

    g.evaluate_once()
    assert g.evaluate_once().action == "would-lock"
    assert g.evaluate_once().state == "present"
    assert g._episode_locked is False
    g.evaluate_once()
    assert g.evaluate_once().action == "would-lock"


def test_absent_starts_grace_clock(tmp_path, monkeypatch):
    _patch_face(monkeypatch, present=False)
    g = _guard(tmp_path, monkeypatch, [True], absent_grace_minutes=5)
    decision = g.evaluate_once()
    assert decision.state == "absent"
    assert decision.action is None
    assert g.absent_since is not None


def test_absent_past_grace_locks(tmp_path, monkeypatch):
    _patch_face(monkeypatch, present=False)
    g = _guard(tmp_path, monkeypatch, [True], absent_grace_minutes=5)
    g.evaluate_once()
    g.absent_since -= 6 * 60
    assert g.evaluate_once().action == "would-lock"


@pytest.mark.parametrize("checks", [1, 2, 3])
def test_impostor_threshold_is_respected(tmp_path, monkeypatch, checks):
    _patch_face(monkeypatch, present=True)
    g = _guard(tmp_path, monkeypatch, [False] * (checks + 1), impostor_checks=checks)
    actions = [g.evaluate_once().action for _ in range(checks)]
    assert actions[-1] == "would-lock"
    assert all(a is None for a in actions[:-1])
