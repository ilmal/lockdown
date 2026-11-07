from __future__ import annotations

from pathlib import Path

from presence_guard import config


def test_defaults_never_expose_the_network():
    cfg = config.Config()
    assert cfg.remote.host != "0.0.0.0"
    assert not cfg.remote.host.startswith("::")


def test_load_missing_file_returns_defaults(tmp_path):
    cfg = config.load(tmp_path / "nope.toml")
    assert cfg.guard.interval_seconds == 300


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
        [camera]
        device = "/dev/video2"
        bogus = 1

        [verify]
        threshold = 55.5
        """
    )
    cfg = config.load(path)
    assert cfg.camera.device == "/dev/video2"
    assert cfg.verify.threshold == 55.5


def test_token_missing_file_is_empty(tmp_path):
    cfg = config.Config()
    cfg.remote.token_file = str(tmp_path / "absent")
    assert cfg.token == ""
