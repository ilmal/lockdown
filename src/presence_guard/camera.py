from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

FACE_SIZE = (100, 100)

# OpenCV 5 dropped the bundled cascades, so ship our own.
CASCADE_PATH = Path(__file__).parent / "data" / "haarcascade_frontalface_default.xml"

_cascade = None


def _detector() -> cv2.CascadeClassifier:
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(str(CASCADE_PATH))
        if _cascade.empty():
            raise RuntimeError(f"could not load Haar cascade from {CASCADE_PATH}")
    return _cascade


def open_camera(device: str, width: int, height: int, warmup: int = 0) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open camera {device}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    for _ in range(max(0, warmup)):
        cap.read()
    return cap


def grab_frame(device: str, width: int, height: int, warmup: int = 4) -> np.ndarray:
    cap = open_camera(device, width, height, warmup)
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"camera {device} returned no frame")
    return frame


def to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


@dataclass
class Face:
    box: tuple[int, int, int, int]
    gray: np.ndarray

    @property
    def area(self) -> int:
        _, _, w, h = self.box
        return w * h


def detect_faces(frame: np.ndarray, min_size: int = 60) -> list[Face]:
    gray = to_gray(frame)
    gray = cv2.equalizeHist(gray)
    boxes = _detector().detectMultiScale(
        gray, scaleFactor=1.15, minNeighbors=5, minSize=(min_size, min_size)
    )
    faces = []
    for x, y, w, h in boxes:
        crop = gray[y : y + h, x : x + w]
        if crop.size == 0:
            continue
        faces.append(Face((int(x), int(y), int(w), int(h)), cv2.resize(crop, FACE_SIZE)))
    faces.sort(key=lambda f: f.area, reverse=True)
    return faces


def largest_face(frame: np.ndarray, min_size: int = 60) -> Face | None:
    faces = detect_faces(frame, min_size=min_size)
    return faces[0] if faces else None


def probe(device: str) -> dict:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            return {"device": device, "open": False}
        ok, frame = cap.read()
        info = {
            "device": device,
            "open": True,
            "frame": ok,
            "shape": tuple(frame.shape) if ok and frame is not None else None,
            "fps": cap.get(cv2.CAP_PROP_FPS),
        }
    finally:
        cap.release()
    return info


def settle(seconds: float = 0.0) -> None:
    if seconds > 0:
        time.sleep(seconds)
