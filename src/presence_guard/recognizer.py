from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import camera, config

MODEL_NAME = "model.yml"
META_NAME = "meta.json"


def model_path() -> Path:
    return config.data_dir() / MODEL_NAME


def meta_path() -> Path:
    return config.data_dir() / META_NAME


def enrolled() -> bool:
    return model_path().exists() and meta_path().exists()


@dataclass
class Result:
    matched: bool
    distance: float
    threshold: float
    label: int

    @property
    def verdict(self) -> str:
        return "match" if self.matched else "impostor"


class Recognizer:
    def __init__(self, threshold: float = 62.0):
        self.threshold = threshold
        self._model: cv2.face.LBPHFaceRecognizer | None = None

    def load(self) -> None:
        path = model_path()
        if not path.exists():
            raise FileNotFoundError(
                f"no enrolled model at {path}; run `presence-guard enroll` first"
            )
        model = cv2.face.LBPHFaceRecognizer_create()
        model.read(str(path))
        self._model = model

    def predict(self, face_gray: np.ndarray) -> Result:
        if self._model is None:
            self.load()
        label, distance = self._model.predict(face_gray)
        return Result(
            matched=float(distance) <= self.threshold,
            distance=float(distance),
            threshold=self.threshold,
            label=int(label),
        )


def enroll_samples(
    cfg: config.Config,
    samples: int,
    show_progress: bool = True,
    allow_multiple_faces: bool = False,
) -> Path:
    out_dir = config.data_dir() / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    cap = camera.open_camera(
        cfg.camera.device, cfg.camera.width, cfg.camera.height, cfg.camera.warmup_frames
    )
    saved = 0
    attempts = 0
    skipped_multi = 0
    try:
        while saved < samples and attempts < samples * 40:
            attempts += 1
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            faces = camera.detect_faces(frame)
            if not faces:
                continue
            # Enrolling whichever face happens to be largest could teach the
            # model the wrong person, so refuse ambiguous scenes by default.
            if len(faces) > 1 and not allow_multiple_faces:
                skipped_multi += 1
                continue
            face = faces[0]
            cv2.imwrite(str(out_dir / f"{saved:03d}.png"), face.gray)
            saved += 1
            if show_progress:
                print(f"\r  captured {saved}/{samples}", end="", flush=True)
    finally:
        cap.release()
    if show_progress:
        print()
    if skipped_multi and show_progress:
        print(
            f"  skipped {skipped_multi} frame(s) with more than one face; "
            "enroll alone, or pass --allow-multiple-faces"
        )
    if saved < max(8, samples // 3):
        raise RuntimeError(
            f"only {saved} usable frames; check lighting and that your face fills the frame"
        )
    return out_dir
    if saved < max(8, samples // 3):
        raise RuntimeError(
            f"only {saved} usable frames; check lighting and that your face fills the frame"
        )
    return out_dir


def train(cfg: config.Config) -> Path:
    sample_dir = config.data_dir() / "samples"
    files = sorted(sample_dir.glob("*.png"))
    if not files:
        raise RuntimeError(f"no samples in {sample_dir}; run `presence-guard enroll` first")

    images = [cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in files]
    images = [i for i in images if i is not None]
    labels = np.zeros(len(images), dtype=np.int32)

    model = cv2.face.LBPHFaceRecognizer_create()
    model.train(images, labels)

    model_path().parent.mkdir(parents=True, exist_ok=True)
    model.write(str(model_path()))
    meta_path().write_text(
        json.dumps({"samples": len(images), "label": 0, "facesize": list(camera.FACE_SIZE)}, indent=2)
    )
    return model_path()
