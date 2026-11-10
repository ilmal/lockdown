"""Face recognition: YuNet detection + SFace embeddings.

Replaces the LBPH matcher, which was a 2004-era texture histogram: on the
reference laptop the same person measured 62-83 with single frames crossing the
threshold constantly. SFace measured 0.53-0.66 cosine against an identical
0.363 cutoff, i.e. a wide margin.

Models are fetched on first use rather than vendored: together they are 37 MB,
which does not belong in a git repository. Checksums are pinned; a mismatch is a
hard error, never a silent downgrade.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import camera, config

MODELS = {
    "yunet": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "sface": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}

# SFace's published cosine cutoff for "same person".
SFACE_COSINE_THRESHOLD = 0.363
EMBEDDING_NAME = "embeddings.npy"
META_NAME = "meta.json"


def model_dir() -> Path:
    return config.data_dir() / "models"


def model_path(key: str) -> Path:
    return model_dir() / f"{key}.onnx"


def embeddings_path() -> Path:
    return config.data_dir() / EMBEDDING_NAME


def meta_path() -> Path:
    return config.data_dir() / META_NAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_models(progress: bool = True) -> None:
    """Download any missing model, verifying a pinned checksum."""
    model_dir().mkdir(parents=True, exist_ok=True)
    for key, (url, expected) in MODELS.items():
        dest = model_path(key)
        if dest.exists() and _sha256(dest) == expected:
            continue
        if progress:
            print(f"downloading {key} model (~{37 if key == 'sface' else 0.2:.0f} MB)…", flush=True)
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        actual = _sha256(tmp)
        if actual != expected:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"checksum mismatch for {key}: expected {expected}, got {actual}"
            )
        tmp.replace(dest)


def enrolled() -> bool:
    return embeddings_path().exists() and meta_path().exists()


@dataclass
class Result:
    matched: bool
    similarity: float
    threshold: float

    @property
    def verdict(self) -> str:
        return "match" if self.matched else "impostor"


class Recognizer:
    """SFace embeddings compared by cosine similarity."""

    def __init__(self, threshold: float = SFACE_COSINE_THRESHOLD):
        self.threshold = threshold
        self._rec = None
        self._refs: np.ndarray | None = None

    def _recognizer(self):
        if self._rec is None:
            ensure_models()
            self._rec = cv2.FaceRecognizerSF.create(str(model_path("sface")), "")
        return self._rec

    def load(self) -> None:
        if not enrolled():
            raise FileNotFoundError(
                "no enrolled face; run `presence-guard enroll` first"
            )
        self._refs = np.load(embeddings_path())

    def _embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        return self._recognizer().feature(aligned_bgr)

    def predict(self, bgr: np.ndarray) -> Result:
        if self._refs is None:
            self.load()
        embedding = self._embed(bgr)
        rec = self._recognizer()
        best = max(
            rec.match(ref, embedding, cv2.FACE_RECOGNIZER_SF_FR_COSINE)
            for ref in self._refs
        )
        return Result(
            matched=bool(best >= self.threshold),
            similarity=float(best),
            threshold=float(self.threshold),
        )


_det_cache: dict = {}
_rec_cache: dict = {}


def _detector(size: tuple[int, int]):
    """Cached detector for a given input size.

    Constructing FaceDetectorYN loads the ONNX graph; doing that per frame
    flooded the log and made the demo unresponsive.
    """
    key = size
    if key not in _det_cache:
        ensure_models()
        _det_cache[key] = cv2.FaceDetectorYN.create(
            str(model_path("yunet")), "", size, score_threshold=0.6, nms_threshold=0.3
        )
    return _det_cache[key]


def _sf_recognizer():
    if "rec" not in _rec_cache:
        ensure_models()
        _rec_cache["rec"] = cv2.FaceRecognizerSF.create(str(model_path("sface")), "")
    return _rec_cache["rec"]


def detect_raw(frame: np.ndarray):
    """YuNet detections including the 5 landmark points, largest first."""
    h, w = frame.shape[:2]
    det = _detector((w, h))
    _, faces = det.detect(frame)
    if faces is None:
        return []
    return sorted(faces, key=lambda f: f[2] * f[3], reverse=True)


def detect(frame: np.ndarray) -> list[tuple[tuple[int, int, int, int], np.ndarray]]:
    """Return (box, crop) for each detected face, largest first."""
    out = []
    for face in detect_raw(frame):
        x, y, fw, fh = (int(v) for v in face[:4])
        crop = frame[max(0, y) : max(0, y) + fh, max(0, x) : max(0, x) + fw]
        if crop.size == 0:
            continue
        out.append(((x, y, fw, fh), crop))
    return out


def largest_face(frame: np.ndarray):
    """Largest detection as (box, aligned_112x112_bgr).

    The crop is landmark-aligned: SFace was trained on aligned faces, and
    feeding it a plain bounding-box crop let a photo of a stranger score 0.47
    against an enrolled face. With alignCrop the same photo scores 0.20.
    """
    faces = detect_raw(frame)
    if not faces:
        return None
    face = faces[0]
    x, y, fw, fh = (int(v) for v in face[:4])
    aligned = _sf_recognizer().alignCrop(frame, face)
    return (x, y, fw, fh), aligned


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
            faces = detect(frame)
            if not faces:
                continue
            if len(faces) > 1 and not allow_multiple_faces:
                skipped_multi += 1
                continue
            box, crop = faces[0]
            x, y, fw, fh = box
            pad = int(0.15 * max(fw, fh))
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1 = min(frame.shape[1], x + fw + pad)
            y1 = min(frame.shape[0], y + fh + pad)
            face = frame[y0:y1, x0:x1]
            cv2.imwrite(str(out_dir / f"{saved:03d}.png"), face)
            saved += 1
            if show_progress:
                print(f"\r  captured {saved}/{samples}", end="", flush=True)
    finally:
        cap.release()
    if show_progress:
        print()
        if skipped_multi:
            print(
                f"  skipped {skipped_multi} frame(s) with more than one face; "
                "enroll alone, or pass --allow-multiple-faces"
            )
    if saved < max(5, samples // 3):
        raise RuntimeError(
            f"only {saved} usable frames; check lighting and that your face fills the frame"
        )
    return out_dir


def train(cfg: config.Config) -> Path:
    sample_dir = config.data_dir() / "samples"
    files = sorted(sample_dir.glob("*.png"))
    if not files:
        raise RuntimeError(f"no samples in {sample_dir}; run `presence-guard enroll` first")

    ensure_models(progress=False)
    rec = _sf_recognizer()
    embeddings = []
    skipped = 0
    for path in files:
        img = cv2.imread(str(path))
        if img is None:
            skipped += 1
            continue
        # Enrolled samples are face crops; re-detect inside them so alignCrop
        # gets the landmark points it needs. A crop without a usable detection
        # is dropped rather than embedded unaligned, which is what let a
        # stranger's photo score as a match.
        faces = detect_raw(img)
        if not faces:
            skipped += 1
            continue
        embeddings.append(rec.feature(rec.alignCrop(img, faces[0])))
    if not embeddings:
        raise RuntimeError(
            "no sample produced a detectable face with landmarks; re-run "
            "`presence-guard enroll` in better light"
        )

    np.save(embeddings_path(), np.vstack(embeddings))
    meta_path().write_text(
        json.dumps(
            {
                "samples": len(embeddings),
                "skipped": skipped,
                "model": "sface",
                "aligned": True,
                "threshold": SFACE_COSINE_THRESHOLD,
            },
            indent=2,
        )
    )
    return embeddings_path()
