# core/camera.py
import sys
from typing import Optional

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False


def open_webcam(index: int = 0) -> Optional["cv2.VideoCapture"]:
    """Open the webcam using the most reliable backend for the platform.

    On Windows, prefers DirectShow (DSHOW) over Media Foundation (MSMF) — DSHOW
    is far more tolerant of transient failures and avoids the cap_msmf.cpp
    `can't grab frame` warning flood (MF_E_HW_MFT_FAILED_START_STREAMING).

    Returns None if the device cannot be opened.
    """
    if not _CV2:
        return None
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return None
    return cap
