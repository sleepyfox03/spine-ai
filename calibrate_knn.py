#!/usr/bin/env python3
"""
calibrate_knn.py — Spine AI KNN Dataset Capture & Training
===========================================================
Pose detection: YOLOv8-pose (ultralytics)

Usage:
    python calibrate_knn.py

Flow:
    1. Opens webcam with YOLOv8 ghost skeleton overlay.
    2. Hold  G  for 5 seconds (≈ 60 frames at 12 fps) → "good" samples.
    3. Hold  B  for 5 seconds                          → "bad"  samples.
    4. Both classes captured → exports to posture_knn_dataset.json.
    5. Trains KNeighborsClassifier (k=5) → saves posture_knn.pkl.
    6. PostureEngine auto-loads posture_knn.pkl on next launch (preferred
       over RandomForest when the KNN model is present).
"""

import os
# Silence OpenCV MSMF warning flood and prefer DirectShow on Windows.
# Must be set BEFORE cv2 is imported.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")

import sys
import json
import time
import pickle
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core.camera import open_webcam

DATASET_PATH = os.path.join(BASE_DIR, "posture_knn_dataset.json")
KNN_PKL_PATH = os.path.join(BASE_DIR, "posture_knn.pkl")

FRAMES_NEEDED = 60   # ≈ 5 seconds at 12 fps

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

try:
    from ultralytics import YOLO as _YOLO
    _YOLO_OK = True
except ImportError:
    _YOLO_OK = False

if not _CV2_OK or not _YOLO_OK:
    missing = []
    if not _CV2_OK:  missing.append("opencv-python")
    if not _YOLO_OK: missing.append("ultralytics")
    print(f"ERROR: Missing packages — pip install {' '.join(missing)}")
    sys.exit(1)

from core.posture_engine import extract_features, _norm_kps

# COCO skeleton pairs (for ghost overlay)
_SKELETON = [
    (0,1),(0,2),(1,3),(2,4),(0,5),(0,6),(5,6),
    (5,7),(7,9),(6,8),(8,10),(5,11),(6,12),(11,12),
    (11,13),(13,15),(12,14),(14,16),
]

_YOLO_WEIGHTS = "yolov8n-pose.pt"


# ── Progress bar ──────────────────────────────────────────────────────────────

def _bar(count: int, total: int = FRAMES_NEEDED, width: int = 28) -> str:
    filled = int(width * count / total)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {count}/{total}"


# ── Ghost skeleton drawing ────────────────────────────────────────────────────

def _draw_ghost(frame: np.ndarray, kps_norm: np.ndarray,
                frame_w: int, frame_h: int):
    kps_px = kps_norm.copy()
    kps_px[:, 0] *= frame_w
    kps_px[:, 1] *= frame_h

    for i, j in _SKELETON:
        x1, y1 = int(kps_px[i, 0]), int(kps_px[i, 1])
        x2, y2 = int(kps_px[j, 0]), int(kps_px[j, 1])
        if (x1, y1) == (0, 0) or (x2, y2) == (0, 0):
            continue
        cv2.line(frame, (x1, y1), (x2, y2), (124, 58, 237), 3, cv2.LINE_AA)

    for i in range(len(kps_px)):
        x, y = int(kps_px[i, 0]), int(kps_px[i, 1])
        if (x, y) == (0, 0):
            continue
        cv2.circle(frame, (x, y), 4, (0, 229, 255), -1, cv2.LINE_AA)


# ── Main capture loop ─────────────────────────────────────────────────────────

def run():
    print("\n╔══════════════════════════════════════════╗")
    print("║   SPINE AI — KNN Posture Calibration     ║")
    print("║   Pose backend: YOLOv8n-pose             ║")
    print("╚══════════════════════════════════════════╝")
    print()
    print("  Hold  G  for GOOD posture  (5 seconds / 60 frames)")
    print("  Hold  B  for BAD  posture  (5 seconds / 60 frames)")
    print("  Press  Q  to quit\n")

    print("  Loading YOLOv8n-pose…", end=" ", flush=True)
    try:
        yolo = _YOLO(_YOLO_WEIGHTS)
        yolo.overrides['verbose'] = False
        print("ready.")
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    cap = open_webcam(0)
    if cap is None:
        print("ERROR: Cannot open camera.")
        sys.exit(1)

    good_samples: list[np.ndarray] = []
    bad_samples:  list[np.ndarray] = []
    collecting: str | None = None

    print("\nCamera ready. Look at the screen and press G or B.\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)
        h, w  = frame.shape[:2]
        kps_norm = None

        try:
            results = yolo(frame, verbose=False, stream=False)
            for result in results:
                if result.keypoints is None:
                    break
                raw = result.keypoints.xy.cpu().numpy()
                if raw.shape[0] == 0:
                    break
                kps_norm = _norm_kps(raw[0], w, h)
                _draw_ghost(frame, kps_norm, w, h)
                break
        except Exception:
            pass

        # Feature collection
        if kps_norm is not None:
            if collecting == 'good' and len(good_samples) < FRAMES_NEEDED:
                good_samples.append(extract_features(kps_norm))
            elif collecting == 'bad' and len(bad_samples) < FRAMES_NEEDED:
                bad_samples.append(extract_features(kps_norm))

        # Key input
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            print("\nAborted.")
            break
        elif key in (ord('g'), ord('G')):
            collecting = 'good' if len(good_samples) < FRAMES_NEEDED else None
        elif key in (ord('b'), ord('B')):
            collecting = 'bad' if len(bad_samples) < FRAMES_NEEDED else None
        elif key in (255, 0):
            collecting = None  # key released

        # Auto-stop when full
        if collecting == 'good' and len(good_samples) >= FRAMES_NEEDED:
            collecting = None
        if collecting == 'bad' and len(bad_samples) >= FRAMES_NEEDED:
            collecting = None

        # HUD overlay
        g_done = len(good_samples) >= FRAMES_NEEDED
        b_done = len(bad_samples)  >= FRAMES_NEEDED

        panel = frame.copy()
        cv2.rectangle(panel, (0, h - 115), (w, h), (5, 10, 6), -1)
        cv2.addWeighted(panel, 0.85, frame, 0.15, 0, frame)

        g_col = (0, 220, 80) if not g_done else (0, 160, 60)
        b_col = (80, 80, 255) if not b_done else (60, 60, 180)

        cv2.putText(frame,
                    f"G  Good  {_bar(len(good_samples))}",
                    (10, h - 82), cv2.FONT_HERSHEY_SIMPLEX, 0.44, g_col, 1)
        cv2.putText(frame,
                    f"B  Bad   {_bar(len(bad_samples))}",
                    (10, h - 57), cv2.FONT_HERSHEY_SIMPLEX, 0.44, b_col, 1)

        if collecting == 'good':
            status, col = "⏺  Capturing GOOD…", (0, 255, 100)
        elif collecting == 'bad':
            status, col = "⏺  Capturing BAD…",  (80, 80, 255)
        elif g_done and b_done:
            status, col = "✓ Done! Training…", (0, 220, 80)
        elif g_done:
            status, col = "Good ✓  Now hold B", (0, 200, 255)
        elif b_done:
            status, col = "Bad  ✓  Now hold G", (0, 200, 255)
        else:
            status, col = "Hold G or B  |  Q=quit", (150, 200, 150)

        cv2.putText(frame, status, (10, h - 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)

        cv2.imshow("SpineAI — KNN Calibration (Q to quit)", frame)

        if g_done and b_done:
            time.sleep(0.4)
            break

    cap.release()
    cv2.destroyAllWindows()

    if len(good_samples) < FRAMES_NEEDED or len(bad_samples) < FRAMES_NEEDED:
        print(
            f"\nInsufficient data  (good={len(good_samples)}, bad={len(bad_samples)}).\n"
            "Run again and hold G / B longer."
        )
        sys.exit(1)

    _train(good_samples, bad_samples)


# ── Training ──────────────────────────────────────────────────────────────────

def _train(good: list[np.ndarray], bad: list[np.ndarray]):
    print(f"\n{'─'*50}")
    print(f"  Good samples : {len(good)}")
    print(f"  Bad  samples : {len(bad)}")
    print(f"{'─'*50}")

    X_good = np.array(good, dtype=np.float32)
    X_bad  = np.array(bad,  dtype=np.float32)
    X      = np.vstack([X_good, X_bad])
    y      = np.array(['good'] * len(good) + ['bad'] * len(bad))

    # Export JSON
    print("  Saving posture_knn_dataset.json …", end=" ", flush=True)
    dataset = {
        'good':            X_good.tolist(),
        'bad':             X_bad.tolist(),
        'feature_names':   ['neck_angle', 'shoulder_tilt',
                            'triangle_area', 'ear_dist'],
        'pose_backend':    'yolov8n-pose',
        'captured_at':     time.strftime("%Y-%m-%d %H:%M:%S"),
        'frames_per_class': FRAMES_NEEDED,
    }
    with open(DATASET_PATH, 'w') as f:
        json.dump(dataset, f, indent=2)
    print("done")

    # Train KNN
    print("  Training KNeighborsClassifier (k=5) …", end=" ", flush=True)
    try:
        from sklearn.neighbors import KNeighborsClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import cross_val_score

        clf = Pipeline([
            ('scaler', StandardScaler()),
            ('knn',    KNeighborsClassifier(
                n_neighbors=5,
                weights='distance',
                metric='euclidean',
            )),
        ])
        clf.fit(X, y)
        print("done")

        scores = cross_val_score(clf, X, y, cv=5, scoring='accuracy')
        print(f"  Cross-val accuracy: "
              f"{scores.mean()*100:.1f}% ± {scores.std()*100:.1f}%")

    except ImportError:
        print("\nERROR: scikit-learn missing — pip install scikit-learn")
        sys.exit(1)

    # Save model
    print(f"  Saving posture_knn.pkl …", end=" ", flush=True)
    with open(KNN_PKL_PATH, 'wb') as f:
        pickle.dump(clf, f)
    print("done")

    print()
    print("╔══════════════════════════════════════════╗")
    print("║   KNN model ready! Launch Spine AI now.  ║")
    print("╚══════════════════════════════════════════╝\n")


if __name__ == "__main__":
    run()
