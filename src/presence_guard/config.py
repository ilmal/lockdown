from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def config_path() -> Path:
    override = os.environ.get("PRESENCE_GUARD_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path("~/.config/presence-guard/config.toml").expanduser()


def data_dir() -> Path:
    override = os.environ.get("PRESENCE_GUARD_DATA")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "presence-guard"


@dataclass
class CameraConfig:
    device: str = "/dev/video0"
    width: int = 640
    height: int = 480
    warmup_frames: int = 4


@dataclass
class VerifyConfig:
    threshold: float = 62.0
    impostor_checks: int = 2
    absent_grace_minutes: int = 5


@dataclass
class GuardConfig:
    interval_seconds: int = 300
    skip_when_locked: bool = True


@dataclass
class RemoteConfig:
    host: str = "127.0.0.1"
    port: int = 8791
    token_file: str = "~/.claude/secrets/presence-guard-token"


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)

    @property
    def token(self) -> str:
        path = Path(self.remote.token_file).expanduser()
        try:
            return path.read_text().strip()
        except OSError:
            return ""


_SECTIONS = {
    "camera": CameraConfig,
    "verify": VerifyConfig,
    "guard": GuardConfig,
    "remote": RemoteConfig,
}


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    cfg = Config()
    if not path.exists():
        return cfg
    raw = tomllib.loads(path.read_text())
    for name, cls in _SECTIONS.items():
        values = raw.get(name) or {}
        known = {f for f in cls.__dataclass_fields__}
        setattr(cfg, name, cls(**{k: v for k, v in values.items() if k in known}))
    return cfg
