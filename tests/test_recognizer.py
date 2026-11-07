from __future__ import annotations

import numpy as np
import pytest

from presence_guard import config, recognizer
from presence_guard.remote import _authorized


def _cfg(tmp_path, monkeypatch, **verify) -> config.Config:
    monkeypatch.setenv("PRESENCE_GUARD_DATA", str(tmp_path / "data"))
    cfg = config.Config()
    for key, value in verify.items():
        setattr(cfg.verify, key, value)
    return cfg


def _write_model(cfg: config.Config) -> None:
    import cv2

    faces, labels = [], []
    rng = np.random.default_rng(0)
    base = np.full((100, 100), 120, dtype=np.uint8)
    for _ in range(12):
        noise = rng.integers(-4, 5, size=(100, 100), dtype=np.int16)
        faces.append(np.clip(base + noise, 0, 255).astype(np.uint8))
        labels.append(0)
    model = cv2.face.LBPHFaceRecognizer_create()
    model.train(faces, np.array(labels, dtype=np.int32))
    path = recognizer.model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(path))
    recognizer.meta_path().write_text("{}")


def test_model_roundtrip_matches_similar_face(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, threshold=1000.0)
    _write_model(cfg)

    rec = recognizer.Recognizer(cfg.verify.threshold)
    rec.load()
    probe = np.full((100, 100), 120, dtype=np.uint8)
    result = rec.predict(probe)

    assert result.label == 0
    assert result.matched is True


def test_impossible_threshold_rejects(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, monkeypatch, threshold=0.0)
    _write_model(cfg)

    rec = recognizer.Recognizer(cfg.verify.threshold)
    rec.load()
    result = rec.predict(np.full((100, 100), 120, dtype=np.uint8))

    assert result.matched is False
    assert result.verdict == "impostor"


def test_load_without_model_raises(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        recognizer.Recognizer(62.0).load()


@pytest.mark.parametrize(
    "header, expected, ok",
    [
        ("Bearer abc", "abc", True),
        ("Bearer abd", "abc", False),
        ("bearer abc", "abc", False),
        (None, "abc", False),
        ("Bearer abc", "", False),
        ("Bearer ", "abc", False),
    ],
)
def test_auth_compares_constantly(header, expected, ok):
    assert _authorized(header, expected) is ok
