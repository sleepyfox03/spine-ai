# core/posture_engine.py
# Precision "Pseudo-3D" posture engine
# Pose detection  : YOLOv8-pose  (ultralytics)
# Blink / EAR     : MediaPipe Face Mesh (468-pt — only use case for mediapipe)
import os
import sys
import time
import pickle
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BASE_DIR

# ── YOLOv8-pose ──────────────────────────────────────────────────────────────
try:
    from ultralytics import YOLO as _YOLO
    _YOLO_AVAILABLE = True
except ImportError:
    _YOLO_AVAILABLE = False

# ── MediaPipe Face Mesh (blink / EAR only) ───────────────────────────────────
try:
    import cv2
    import mediapipe as mp
    _FACE_AVAILABLE = True
except ImportError:
    _FACE_AVAILABLE = False

MODEL_PATH       = os.path.join(BASE_DIR, "posture_model.pkl")
KNN_MODEL_PATH   = os.path.join(BASE_DIR, "posture_knn.pkl")
CALIBRATION_PATH = os.path.join(BASE_DIR, "calibration_profile.json")

# ── YOLO COCO 17-pt keypoint indices ─────────────────────────────────────────
#   0:nose  1:l_eye  2:r_eye  3:l_ear  4:r_ear
#   5:l_sh  6:r_sh   7:l_elb  8:r_elb  9:l_wri 10:r_wri
#  11:l_hip 12:r_hip 13:l_kne 14:r_kne 15:l_ank 16:r_ank
_KP_NOSE    = 0
_KP_L_EYE   = 1
_KP_R_EYE   = 2
_KP_L_EAR   = 3
_KP_R_EAR   = 4
_KP_L_SH    = 5
_KP_R_SH    = 6

# YOLO model weights (nano = fastest; swap to yolov8s-pose.pt for more accuracy)
_YOLO_WEIGHTS = "yolov8n-pose.pt"

# ── Face Mesh EAR landmark indices (MediaPipe 468-pt) ─────────────────────────
# Spec: vertical=(159,145), horizontal=(33,133) for left eye
#       symmetric for right eye
_L_EYE_TOP,   _L_EYE_BOT  = 159, 145
_L_EYE_OUTER, _L_EYE_INN  = 33,  133
_R_EYE_TOP,   _R_EYE_BOT  = 386, 374
_R_EYE_OUTER, _R_EYE_INN  = 263, 362


# ── YOLO skeleton connections (COCO pairs for annotation) ─────────────────────
_YOLO_SKELETON = [
    (0, 1), (0, 2),          # nose → eyes
    (1, 3), (2, 4),          # eyes → ears
    (0, 5), (0, 6),          # nose → shoulders
    (5, 6),                  # shoulder bar
    (5, 7), (7, 9),          # left arm
    (6, 8), (8, 10),         # right arm
    (5, 11), (6, 12),        # torso
    (11, 12),                # hip bar
    (11, 13), (13, 15),      # left leg
    (12, 14), (14, 16),      # right leg
]


@dataclass
class PostureResult:
    timestamp:        str
    score:            float    # 0–100
    label:            str      # 'Good' | 'Slouch' | 'Forward Head' | 'Lateral Tilt'
    neck_angle:       float    # degrees — forward deviation from vertical
    shoulder_tilt:    float    # normalised y-diff × 1000
    triangle_area:    float    # nose–L.shoulder–R.shoulder area × 10000
    depth_cm:         float    = 60.0
    fhp_offset:       float    = 0.0
    chin_jutting:     bool     = False
    lateral_tilt:     float    = 0.0
    ear_y_diff:       float    = 0.0
    slouch_type:      str      = ''
    frame_annotated:  Optional[Any] = field(default=None, repr=False)


@dataclass
class EyeResult:
    timestamp:          str
    blink_rate:         float   # blinks / min (rolling 60 s window)
    screen_distance_cm: float
    strain_score:       float   # 0–100


# ── Keypoint normaliser ───────────────────────────────────────────────────────

def _norm_kps(raw_kps: np.ndarray, frame_w: int, frame_h: int) -> np.ndarray:
    """
    Convert YOLO pixel keypoints  shape (17, 2) or (17, 3)
    to normalised (17, 2) array in 0-1 range — same coordinate space
    as the old MediaPipe landmark .x / .y attributes.

    raw_kps columns: [x_px, y_px]  or  [x_px, y_px, confidence]
    """
    kps = raw_kps[:, :2].copy().astype(np.float32)
    kps[:, 0] /= max(frame_w, 1)
    kps[:, 1] /= max(frame_h, 1)
    return kps


# ── Feature extraction (shared with calibration & KNN script) ─────────────────

def extract_features(kps: np.ndarray) -> np.ndarray:
    """
    Extract [neck_angle, shoulder_tilt, triangle_area, ear_dist] from a
    normalised (17, 2) keypoints array (COCO format, 0-1 range).

    Replaces the old (lm, PL) MediaPipe signature — all math is identical.
    """
    nose  = kps[_KP_NOSE]
    l_sh  = kps[_KP_L_SH]
    r_sh  = kps[_KP_R_SH]
    l_ear = kps[_KP_L_EAR]
    r_ear = kps[_KP_R_EAR]

    sh_mid  = (l_sh + r_sh) / 2
    ear_mid = (l_ear + r_ear) / 2

    # 1. Neck angle — forward-head deviation from vertical (°)
    dy = abs(sh_mid[1] - nose[1])
    dx = abs(nose[0]   - sh_mid[0])
    neck_angle = float(np.degrees(np.arctan2(dx, dy + 1e-6)))

    # 2. Shoulder tilt — y-axis asymmetry (scaled × 1000)
    shoulder_tilt = float(abs(l_sh[1] - r_sh[1]) * 1000)

    # 3. Triangle area (nose – left shoulder – right shoulder)
    triangle_area = float(
        0.5 * abs(
            (l_sh[0] - nose[0]) * (r_sh[1] - nose[1]) -
            (r_sh[0] - nose[0]) * (l_sh[1] - nose[1])
        ) * 10_000
    )

    # 4. Ear-midpoint → shoulder-midpoint distance (forward-head indicator)
    ear_dist = float(np.linalg.norm(ear_mid - sh_mid) * 1000)

    return np.array([neck_angle, shoulder_tilt, triangle_area, ear_dist],
                    dtype=np.float32)


def extract_pseudo3d(kps: np.ndarray, frame_w: int, frame_h: int) -> dict:
    """
    Compute Pseudo-3D metrics from normalised COCO keypoints.
    Identical logic to the MediaPipe version — only the indexing changed.
    """
    nose  = kps[_KP_NOSE]
    l_sh  = kps[_KP_L_SH]
    r_sh  = kps[_KP_R_SH]
    l_ear = kps[_KP_L_EAR]
    r_ear = kps[_KP_R_EAR]
    l_eye = kps[_KP_L_EYE]
    r_eye = kps[_KP_R_EYE]

    # ── Depth from eye IPD ────────────────────────────────────────────────────
    eye_dist_px = float(np.linalg.norm(l_eye - r_eye)) * frame_w
    FOCAL_EYE_CM = 6.3 * 600
    depth_cm = float(np.clip(FOCAL_EYE_CM / (eye_dist_px + 1e-4), 20.0, 150.0))

    # ── Forward Head Posture (FHP) ────────────────────────────────────────────
    sh_mid  = (l_sh + r_sh) / 2
    ear_mid = (l_ear + r_ear) / 2

    fhp_offset  = float((sh_mid[0] - ear_mid[0]) * 1000)
    nose_to_ear_x = float((nose[0] - ear_mid[0]) * 1000)
    chin_jutting  = nose_to_ear_x > 15.0

    # ── Lateral Spinal Curvature ──────────────────────────────────────────────
    lateral_tilt = float((r_sh[1]  - l_sh[1])  * 1000)
    ear_y_diff   = float((r_ear[1] - l_ear[1]) * 1000)

    # ── Slouch type ───────────────────────────────────────────────────────────
    if fhp_offset > 40 or chin_jutting:
        slouch_type = 'fhp'
    elif abs(lateral_tilt) > 20 or abs(ear_y_diff) > 20:
        slouch_type = 'lateral'
    else:
        slouch_type = ''

    return {
        'depth_cm':     round(depth_cm, 1),
        'fhp_offset':   round(fhp_offset, 1),
        'chin_jutting': chin_jutting,
        'lateral_tilt': round(lateral_tilt, 1),
        'ear_y_diff':   round(ear_y_diff, 1),
        'slouch_type':  slouch_type,
    }


# ── Rule-based fallback ───────────────────────────────────────────────────────

def rule_based_classify(neck_angle: float, shoulder_tilt: float,
                         ear_dist: float, sensitivity: float = 1.0,
                         p3d: Optional[dict] = None) -> tuple[str, float]:
    sf = max(0.1, min(2.0, sensitivity))

    FHP_NECK_THRESH  = 25.0 / sf
    FHP_DIST_THRESH  = 130.0 / sf
    SLOUCH_NECK      = 18.0 / sf
    SLOUCH_TILT      = 10.0 / sf
    LATERAL_THRESH   = 20.0 / sf

    is_lateral = False
    if p3d:
        is_lateral = (abs(p3d.get('lateral_tilt', 0)) > LATERAL_THRESH or
                      abs(p3d.get('ear_y_diff',   0)) > LATERAL_THRESH)

    if p3d and (p3d.get('fhp_offset', 0) > 40.0 / sf or p3d.get('chin_jutting', False)):
        label = 'Forward Head'
        score = max(0.0, 100 - (neck_angle - 12) * 3.2 - shoulder_tilt * 0.4)
    elif neck_angle > FHP_NECK_THRESH or ear_dist > FHP_DIST_THRESH:
        label = 'Forward Head'
        score = max(0.0, 100 - (neck_angle - 12) * 3.2 - shoulder_tilt * 0.4)
    elif is_lateral:
        label = 'Lateral Tilt'
        score = max(0.0, 100 - abs(p3d.get('lateral_tilt', 0)) * 2.0
                    - abs(p3d.get('ear_y_diff', 0)) * 1.5)
    elif neck_angle > SLOUCH_NECK or shoulder_tilt > SLOUCH_TILT:
        label = 'Slouch'
        score = max(0.0, 100 - (neck_angle - 10) * 2.5 - shoulder_tilt * 0.7)
    else:
        label = 'Good'
        score = min(100.0, 100 - neck_angle * 1.4 - shoulder_tilt * 0.25)

    return label, float(max(0.0, min(100.0, score)))


# ── Skeleton annotation helper ────────────────────────────────────────────────

def _draw_yolo_skeleton(frame: np.ndarray, kps_norm: np.ndarray,
                        frame_w: int, frame_h: int):
    """Draw the COCO 17-pt skeleton on frame using our neon green theme."""
    # Convert normalised → pixel for drawing
    kps_px = kps_norm.copy()
    kps_px[:, 0] *= frame_w
    kps_px[:, 1] *= frame_h

    joint_color = (0, 255, 102)
    bone_color  = (0, 200, 70)

    for i, j in _YOLO_SKELETON:
        x1, y1 = int(kps_px[i, 0]), int(kps_px[i, 1])
        x2, y2 = int(kps_px[j, 0]), int(kps_px[j, 1])
        # Skip if keypoint is at origin (YOLO marks undetected as 0,0)
        if (x1, y1) == (0, 0) or (x2, y2) == (0, 0):
            continue
        cv2.line(frame, (x1, y1), (x2, y2), bone_color, 2, cv2.LINE_AA)

    for i in range(len(kps_px)):
        x, y = int(kps_px[i, 0]), int(kps_px[i, 1])
        if (x, y) == (0, 0):
            continue
        cv2.circle(frame, (x, y), 3, joint_color, -1, cv2.LINE_AA)


# ── Main Engine ───────────────────────────────────────────────────────────────

class PostureEngine:
    """
    High-precision Pseudo-3D posture engine.
    Pose detection  → YOLOv8-pose (ultralytics)
    Blink / EAR     → MediaPipe Face Mesh (kept for 468-pt eye landmarks)

    Args:
        sensitivity_factor: float 0.1–2.0 (default 1.0)
    """

    def __init__(self, sensitivity_factor: float = 1.0):
        self.sensitivity_factor = float(np.clip(sensitivity_factor, 0.1, 2.0))
        self._model     = self._load_pkl(MODEL_PATH)
        self._knn_model = self._load_pkl(KNN_MODEL_PATH)

        # Blink state
        self._blink_closed     = False
        self._blink_timestamps: list[float] = []

        # ── YOLOv8-pose ───────────────────────────────────────────────────────
        self._yolo = None
        if _YOLO_AVAILABLE:
            try:
                self._yolo = _YOLO(_YOLO_WEIGHTS)
                # Warm-up: suppress first-run download chatter
                self._yolo.overrides['verbose'] = False
            except Exception as e:
                print(f"[PostureEngine] YOLO init failed: {e}")

        # ── MediaPipe Face Mesh (blink only) ──────────────────────────────────
        self._face = None
        if _FACE_AVAILABLE:
            try:
                _mp_face = mp.solutions.face_mesh
                self._face = _mp_face.FaceMesh(
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.6,
                    min_tracking_confidence=0.6,
                )
            except Exception as e:
                print(f"[PostureEngine] Face Mesh init failed: {e}")

    # ── Model I/O ─────────────────────────────────────────────────────────────

    @staticmethod
    def _load_pkl(path: str):
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    return pickle.load(f)
            except Exception:
                pass
        return None

    def reload_model(self):
        """Hot-swap classifiers after fresh calibration."""
        self._model     = self._load_pkl(MODEL_PATH)
        self._knn_model = self._load_pkl(KNN_MODEL_PATH)

    def set_sensitivity(self, value: float):
        self.sensitivity_factor = float(np.clip(value, 0.1, 2.0))

    # ── Classifier ────────────────────────────────────────────────────────────

    def _ml_classify(self, features: np.ndarray,
                     neck_angle: float) -> tuple[str, float]:
        """Try KNN first, then RandomForest, with forward-head override."""
        model = self._knn_model or self._model
        if model is None:
            return None, None
        try:
            raw_label = model.predict(features.reshape(1, -1))[0]
            proba     = model.predict_proba(features.reshape(1, -1))[0]
            classes   = list(model.classes_)

            sf = self.sensitivity_factor
            if neck_angle > 25.0 / sf:
                label = 'Forward Head'
            elif raw_label.lower() == 'good':
                label = 'Good'
            else:
                label = 'Slouch'

            good_idx = next((i for i, c in enumerate(classes)
                             if c.lower() == 'good'), 0)
            score = float(proba[good_idx] * 100)
            return label, score
        except Exception:
            return None, None

    # ── EAR blink (Face Mesh) ─────────────────────────────────────────────────

    @staticmethod
    def _ear_4pt(lm, top_i: int, bot_i: int,
                 outer_i: int, inner_i: int) -> float:
        """EAR = vertical / horizontal  using 4 specific Face Mesh points."""
        v = abs(lm[top_i].y - lm[bot_i].y)
        h = abs(lm[outer_i].x - lm[inner_i].x)
        return float(v / (h + 1e-6))

    # ── Main process ──────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray) -> tuple[PostureResult, EyeResult]:
        from datetime import datetime
        ts = datetime.now().isoformat()
        h, w = frame.shape[:2]

        annotated = frame.copy()

        # ── YOLOv8-pose — body keypoints ──────────────────────────────────────
        score, label = 50.0, 'Good'
        neck_ang = sh_tilt = tri_area = 0.0
        p3d: dict = {}

        if self._yolo is not None:
            try:
                results = self._yolo(frame, verbose=False, stream=False)
                for result in results:
                    if result.keypoints is None:
                        continue
                    kps_raw = result.keypoints.xy.cpu().numpy()  # shape (N,17,2)
                    if kps_raw.shape[0] == 0:
                        continue

                    # Use the first (most confident) person
                    raw = kps_raw[0]          # (17, 2) in pixel coords
                    kps = _norm_kps(raw, w, h) # (17, 2) normalised 0-1

                    feats    = extract_features(kps)
                    neck_ang = float(feats[0])
                    sh_tilt  = float(feats[1])
                    tri_area = float(feats[2])
                    ear_dist = float(feats[3])

                    p3d = extract_pseudo3d(kps, w, h)

                    # Classify
                    ml_label, ml_score = self._ml_classify(feats, neck_ang)
                    if ml_label:
                        label, score = ml_label, ml_score
                        if p3d['slouch_type'] == 'lateral' and label == 'Slouch':
                            label = 'Lateral Tilt'
                    else:
                        label, score = rule_based_classify(
                            neck_ang, sh_tilt, ear_dist,
                            sensitivity=self.sensitivity_factor, p3d=p3d
                        )

                    # Draw skeleton
                    _draw_yolo_skeleton(annotated, kps, w, h)
                    break   # only process the first person

            except Exception as e:
                print(f"[PostureEngine] YOLO inference error: {e}")

        posture = PostureResult(
            timestamp     = ts,
            score         = round(score, 1),
            label         = label,
            neck_angle    = round(neck_ang, 1),
            shoulder_tilt = round(sh_tilt, 1),
            triangle_area = round(tri_area, 1),
            depth_cm      = p3d.get('depth_cm', 60.0),
            fhp_offset    = p3d.get('fhp_offset', 0.0),
            chin_jutting  = p3d.get('chin_jutting', False),
            lateral_tilt  = p3d.get('lateral_tilt', 0.0),
            ear_y_diff    = p3d.get('ear_y_diff', 0.0),
            slouch_type   = p3d.get('slouch_type', ''),
            frame_annotated = annotated,
        )

        # ── MediaPipe Face Mesh — blink / EAR ────────────────────────────────
        # Sentinel -1.0 means Face Mesh is unavailable (e.g., Python 3.13 where
        # mediapipe.solutions is missing). The EyeHealthTab renders "—" for it.
        blink_rate = -1.0 if self._face is None else 15.0
        # Fall back to YOLO eye-keypoint depth so the Screen Distance card stays
        # live even when Face Mesh is unavailable.
        dist_cm    = posture.depth_cm
        strain     = 20.0

        if self._face is not None and _FACE_AVAILABLE:
            try:
                rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_res = self._face.process(rgb)

                if face_res.multi_face_landmarks:
                    fl = face_res.multi_face_landmarks[0].landmark

                    ear_l = self._ear_4pt(fl, _L_EYE_TOP, _L_EYE_BOT,
                                          _L_EYE_OUTER, _L_EYE_INN)
                    ear_r = self._ear_4pt(fl, _R_EYE_TOP, _R_EYE_BOT,
                                          _R_EYE_OUTER, _R_EYE_INN)
                    avg_ear = (ear_l + ear_r) / 2.0

                    BLINK_THRESH = 0.20
                    if avg_ear < BLINK_THRESH and not self._blink_closed:
                        self._blink_closed = True
                        self._blink_timestamps.append(time.time())
                    elif avg_ear >= BLINK_THRESH:
                        self._blink_closed = False

                    now = time.time()
                    self._blink_timestamps = [t for t in self._blink_timestamps
                                              if now - t <= 60.0]
                    blink_rate = float(len(self._blink_timestamps))

                    xs = [lm.x for lm in fl]
                    fw = max(xs) - min(xs)
                    if fw > 0.01:
                        dist_cm = float(np.clip(
                            14.0 / (fw * w) * 95.0, 20.0, 120.0
                        ))

                    blink_deficit = max(0.0, 15.0 - blink_rate) / 15.0 * 50.0
                    dist_penalty  = (
                        (45.0 - dist_cm) / 45.0 * 30.0 if dist_cm < 45 else
                        (dist_cm - 80.0) / 40.0 * 20.0 if dist_cm > 80 else 0.0
                    )
                    strain = float(min(100.0, blink_deficit + dist_penalty))
            except Exception as e:
                print(f"[PostureEngine] Face Mesh error: {e}")

        eye = EyeResult(
            timestamp          = ts,
            blink_rate         = round(blink_rate, 1),
            screen_distance_cm = round(dist_cm, 1),
            strain_score       = round(strain, 1),
        )

        return posture, eye

    def release(self):
        if self._face:
            try:
                self._face.close()
            except Exception:
                pass
