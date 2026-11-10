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


@pytest.fixture(scope="module")
def face_like():
    """A synthetic image is useless for a real detector, so skip if no model."""
    pytest.importorskip("cv2")
    return None


def test_result_verdict_uses_similarity_floor():
    ok = recognizer.Result(matched=True, similarity=0.8, threshold=0.4)
    bad = recognizer.Result(matched=False, similarity=0.1, threshold=0.4)
    assert ok.verdict == "match"
    assert bad.verdict == "impostor"


def test_threshold_default_is_sface_cutoff():
    assert 0.36 <= config.Config().verify.threshold <= 0.5


def test_load_without_enrollment_raises(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        recognizer.Recognizer(0.4).load()


def test_enrolled_reflects_files(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    assert recognizer.enrolled() is False
    recognizer.embeddings_path().parent.mkdir(parents=True, exist_ok=True)
    np.save(recognizer.embeddings_path(), np.zeros((3, 128), dtype=np.float32))
    recognizer.meta_path().write_text("{}")
    assert recognizer.enrolled() is True


def test_model_urls_and_checksums_are_pinned():
    for key, (url, digest) in recognizer.MODELS.items():
        assert url.startswith("https://")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


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
