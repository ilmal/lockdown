from __future__ import annotations

import numpy as np

from presence_guard import camera


def test_to_gray_passthrough():
    gray = np.zeros((10, 10), dtype=np.uint8)
    assert camera.to_gray(gray).shape == (10, 10)


def test_to_gray_converts_bgr():
    bgr = np.zeros((10, 10, 3), dtype=np.uint8)
    assert camera.to_gray(bgr).shape == (10, 10)


def test_detect_faces_on_blank_frame_is_empty():
    assert camera.detect_faces(np.zeros((360, 640), dtype=np.uint8)) == []
