# core/calibration.py
# Calibration Wizard — pose detection via YOLOv8-pose (ultralytics)
# Face Mesh is NOT needed here (blink tracking is only in PostureEngine)
import os
import sys
import csv
import json
import threading
import numpy as np
import customtkinter as ctk
import tkinter as tk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *

try:
    import cv2
    from PIL import Image, ImageTk
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

from core.camera import open_webcam

# Calibration feed-loop tuning
_CAL_BACKOFF_AFTER = 5    # consecutive fails → switch from 33ms to 500ms ticks
_CAL_REOPEN_AFTER  = 30   # consecutive fails → release + reopen capture
_CAL_SPINNER_GLYPHS = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

try:
    from ultralytics import YOLO as _YOLO
    _YOLO_AVAILABLE = True
except ImportError:
    _YOLO_AVAILABLE = False

CALIBRATION_PATH = os.path.join(BASE_DIR, "calibration_profile.json")
DATASET_PATH     = os.path.join(BASE_DIR, "calibration_dataset.csv")
MODEL_PATH       = os.path.join(BASE_DIR, "posture_model.pkl")

FRAMES_NEEDED  = 100   # frames per class
_YOLO_WEIGHTS  = "yolov8n-pose.pt"

# COCO keypoint indices (mirrors posture_engine.py)
_KP_NOSE, _KP_L_EYE, _KP_R_EYE = 0, 1, 2
_KP_L_EAR, _KP_R_EAR            = 3, 4
_KP_L_SH,  _KP_R_SH             = 5, 6

# COCO skeleton pairs for ghost overlay
_SKELETON = [
    (0,1),(0,2),(1,3),(2,4),(0,5),(0,6),(5,6),
    (5,7),(7,9),(6,8),(8,10),(5,11),(6,12),(11,12),
    (11,13),(13,15),(12,14),(14,16),
]


def _norm_kps(raw: np.ndarray, w: int, h: int) -> np.ndarray:
    """Pixel (17,2) → normalised (17,2) in 0-1 range."""
    kps = raw[:, :2].copy().astype(np.float32)
    kps[:, 0] /= max(w, 1)
    kps[:, 1] /= max(h, 1)
    return kps


def _draw_ghost_skeleton(frame: np.ndarray, kps_norm: np.ndarray,
                          frame_w: int, frame_h: int):
    """Violet/cyan ghost skeleton for the calibration live view."""
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


class CalibrationWizard(ctk.CTkToplevel):
    """
    3-step calibration wizard (YOLOv8-pose edition).

    Step 1 — Welcome.
    Step 2 — Live webcam + YOLO ghost skeleton.
              Hold G → 100 'good' frames.  Hold B → 100 'bad' frames.
    Step 3 — Train RandomForestClassifier; save model + dataset CSV.
    """

    def __init__(self, parent=None, on_complete=None):
        super().__init__(parent)
        self.on_complete = on_complete
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=BG_PRIMARY)

        w, h = 840, 660
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        # State
        self._running    = False
        self._cap        = None
        self._yolo       = None          # YOLOv8-pose model
        self._photo      = None
        self._collecting = None          # 'good' | 'bad' | None
        self._dataset: list[tuple[np.ndarray, str]] = []
        self._good_count = 0
        self._bad_count  = 0

        # Camera read-failure tracking (drives reconnect UI + backoff)
        self._consec_fail = 0
        self._spin_idx    = 0

        self._build_step1()

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _header(self, title: str):
        ctk.CTkLabel(
            self, text="⬡  SPINE AI  —  Calibration",
            font=FONT_HEADING, text_color=ACCENT_PRIMARY
        ).pack(pady=(24, 4))
        ctk.CTkLabel(
            self, text=title,
            font=FONT_DISPLAY, text_color=TEXT_PRIMARY
        ).pack(pady=(0, 8))

    # ── Step 1 — Welcome ──────────────────────────────────────────────────────

    def _build_step1(self):
        self._clear()
        self._header("Train Your Posture Model")

        ctk.CTkLabel(
            self,
            text=(
                "Spine AI trains a personalised RandomForest model on your posture.\n"
                "You will label 100 frames of Good Posture and 100 of Bad Posture.\n"
                "Takes ≈ 30 seconds — just press G or B while looking at the camera.\n\n"
                "Pose detection powered by  YOLOv8-pose  (ultralytics)."
            ),
            font=FONT_BODY, text_color=TEXT_SECONDARY, justify="center",
        ).pack(pady=(0, 20))

        c = ctk.CTkCanvas(self, width=200, height=180,
                          bg=BG_PRIMARY, highlightthickness=0)
        c.pack()
        self._draw_spine_illus(c)

        ctk.CTkButton(
            self, text="Start Dataset Capture →",
            font=FONT_HEADING,
            fg_color=ACCENT_PRIMARY, text_color=BG_PRIMARY,
            hover_color="#00cc55", width=260, height=48, corner_radius=24,
            command=self._build_step2,
        ).pack(pady=24)

    def _draw_spine_illus(self, c: ctk.CTkCanvas):
        cx = 100
        g  = ACCENT_PRIMARY
        c.create_oval(cx - 18, 6,  cx + 18, 34, fill=BG_CARD, outline=g, width=2)
        c.create_text(cx, 20, text="😐", font=("Arial", 12))
        for i in range(7):
            y = 40 + i * 18
            c.create_rectangle(cx - 12, y, cx + 12, y + 12,
                               fill=BG_CARD, outline=g, width=1)
        for i in range(6):
            y = 52 + i * 18
            c.create_oval(cx - 8, y, cx + 8, y + 6, fill=g, outline="")
        c.create_line(cx - 12, 52, cx - 40, 82, fill=TEXT_SECONDARY, width=2)
        c.create_line(cx + 12, 52, cx + 40, 82, fill=TEXT_SECONDARY, width=2)

    # ── Step 2 — Capture ──────────────────────────────────────────────────────

    def _build_step2(self):
        self._clear()
        self._header("Capture Your Posture Data")

        ctk.CTkLabel(
            self,
            text=(
                "Hold  G  for Good Posture (sit tall, relax)  ·  "
                "Hold  B  for Bad Posture (slouch naturally)\n"
                "Each needs 100 frames. Release key to pause."
            ),
            font=FONT_BODY, text_color=TEXT_SECONDARY, justify="center",
        ).pack(pady=(0, 8))

        self.cam_label = ctk.CTkLabel(self, text="", width=480, height=320)
        self.cam_label.pack()

        # Progress bars
        pb_row = ctk.CTkFrame(self, fg_color="transparent")
        pb_row.pack(fill="x", padx=80, pady=(10, 4))
        pb_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(pb_row, text="G  Good Posture",
                     font=FONT_BODY, text_color=ACCENT_PRIMARY
                     ).grid(row=0, column=0, sticky="w", padx=10)
        self.pb_good = ctk.CTkProgressBar(
            pb_row, width=200, height=8,
            fg_color=BG_SECONDARY, progress_color=ACCENT_PRIMARY)
        self.pb_good.set(0)
        self.pb_good.grid(row=1, column=0, padx=10, sticky="ew")
        self.lbl_g = ctk.CTkLabel(pb_row, text="0 / 100",
                                   font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.lbl_g.grid(row=2, column=0, padx=10, sticky="w")

        ctk.CTkLabel(pb_row, text="B  Bad Posture",
                     font=FONT_BODY, text_color=ACCENT_RED
                     ).grid(row=0, column=1, sticky="w", padx=10)
        self.pb_bad = ctk.CTkProgressBar(
            pb_row, width=200, height=8,
            fg_color=BG_SECONDARY, progress_color=ACCENT_RED)
        self.pb_bad.set(0)
        self.pb_bad.grid(row=1, column=1, padx=10, sticky="ew")
        self.lbl_b = ctk.CTkLabel(pb_row, text="0 / 100",
                                   font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.lbl_b.grid(row=2, column=1, padx=10, sticky="w")

        self.status_lbl = ctk.CTkLabel(
            self, text="Initialising YOLOv8-pose…",
            font=FONT_BODY, text_color=ACCENT_PRIMARY)
        self.status_lbl.pack(pady=(8, 4))

        if not _CV2_AVAILABLE or not _YOLO_AVAILABLE:
            missing = []
            if not _CV2_AVAILABLE:  missing.append("opencv-python")
            if not _YOLO_AVAILABLE: missing.append("ultralytics")
            self.status_lbl.configure(
                text=f"⚠  Missing: {', '.join(missing)} — using mock calibration."
            )
            ctk.CTkButton(
                self, text="Use Mock Calibration",
                font=FONT_BODY,
                fg_color=ACCENT_PRIMARY, text_color=BG_PRIMARY,
                command=self._mock_calibration,
            ).pack(pady=8)
            return

        # Load YOLO in a background thread to avoid UI freeze
        threading.Thread(target=self._init_yolo, daemon=True).start()

    def _init_yolo(self):
        """Load YOLOv8-pose off the UI thread."""
        try:
            self._yolo = _YOLO(_YOLO_WEIGHTS)
            self._yolo.overrides['verbose'] = False
        except Exception as e:
            self.after(0, lambda: self.status_lbl.configure(
                text=f"⚠  YOLO load failed: {e} — using mock calibration."
            ))
            self.after(0, lambda: ctk.CTkButton(
                self, text="Use Mock Calibration",
                font=FONT_BODY,
                fg_color=ACCENT_PRIMARY, text_color=BG_PRIMARY,
                command=self._mock_calibration,
            ).pack(pady=8))
            return

        self._cap = open_webcam(0)
        if self._cap is None:
            self.after(0, lambda: self.status_lbl.configure(
                text="⚠  Camera unavailable — using mock calibration."
            ))
            self.after(0, lambda: ctk.CTkButton(
                self, text="Use Mock Calibration",
                font=FONT_BODY,
                fg_color=ACCENT_PRIMARY, text_color=BG_PRIMARY,
                command=self._mock_calibration,
            ).pack(pady=8))
            return

        self._running = True
        self.after(0, lambda: self.status_lbl.configure(
            text="Ready  ·  Hold G (Good Posture) or B (Bad Posture)"
        ))

        # Key bindings
        self.after(0, self._bind_keys)
        self.after(0, self._feed_loop)

    def _bind_keys(self):
        self.bind("<KeyPress-g>",   lambda _: self._set_collecting('good'))
        self.bind("<KeyPress-G>",   lambda _: self._set_collecting('good'))
        self.bind("<KeyRelease-g>", lambda _: self._stop_collecting())
        self.bind("<KeyRelease-G>", lambda _: self._stop_collecting())
        self.bind("<KeyPress-b>",   lambda _: self._set_collecting('bad'))
        self.bind("<KeyPress-B>",   lambda _: self._set_collecting('bad'))
        self.bind("<KeyRelease-b>", lambda _: self._stop_collecting())
        self.bind("<KeyRelease-B>", lambda _: self._stop_collecting())
        self.focus_set()

    # ── Live feed loop ────────────────────────────────────────────────────────

    def _feed_loop(self):
        if not self._running or self._cap is None or self._yolo is None:
            return

        ret, frame = self._cap.read()
        if not ret:
            self._consec_fail += 1
            if self._consec_fail >= _CAL_BACKOFF_AFTER:
                self._spin_idx = (self._spin_idx + 1) % len(_CAL_SPINNER_GLYPHS)
                self.status_lbl.configure(
                    text=f"{_CAL_SPINNER_GLYPHS[self._spin_idx]}  Reconnecting camera…",
                    text_color=ACCENT_PRIMARY,
                )
            if self._consec_fail == _CAL_REOPEN_AFTER:
                try:
                    if self._cap is not None:
                        self._cap.release()
                except Exception:
                    pass
                self._cap = open_webcam(0)
            if self._running:
                delay = 500 if self._consec_fail >= _CAL_BACKOFF_AFTER else 33
                self.after(delay, self._feed_loop)
            return

        # Successful read — clear reconnect state if we just recovered
        if self._consec_fail:
            self._consec_fail = 0
            self._spin_idx    = 0
            self._update_status()

        if ret:
            h, w = frame.shape[:2]
            kps_norm = None

            try:
                results = self._yolo(frame, verbose=False, stream=False)
                for result in results:
                    if result.keypoints is None:
                        break
                    kps_raw = result.keypoints.xy.cpu().numpy()
                    if kps_raw.shape[0] == 0:
                        break
                    kps_norm = _norm_kps(kps_raw[0], w, h)
                    _draw_ghost_skeleton(frame, kps_norm, w, h)
                    break
            except Exception:
                pass

            # Collect features if user is pressing G or B
            if kps_norm is not None and self._collecting in ('good', 'bad'):
                from core.posture_engine import extract_features
                feats = extract_features(kps_norm)
                self._dataset.append((feats, self._collecting))

                if self._collecting == 'good':
                    self._good_count = min(self._good_count + 1, FRAMES_NEEDED)
                    self.pb_good.set(self._good_count / FRAMES_NEEDED)
                    self.lbl_g.configure(text=f"{self._good_count} / {FRAMES_NEEDED}")
                    if self._good_count >= FRAMES_NEEDED:
                        self._collecting = None
                        self._update_status()
                else:
                    self._bad_count = min(self._bad_count + 1, FRAMES_NEEDED)
                    self.pb_bad.set(self._bad_count / FRAMES_NEEDED)
                    self.lbl_b.configure(text=f"{self._bad_count} / {FRAMES_NEEDED}")
                    if self._bad_count >= FRAMES_NEEDED:
                        self._collecting = None
                        self._update_status()

            # Both classes done → proceed to training
            if self._good_count >= FRAMES_NEEDED and self._bad_count >= FRAMES_NEEDED:
                self._running = False
                if self._cap:
                    self._cap.release()
                self.after(200, self._build_step3)
                return

            # Display frame
            resized     = cv2.resize(frame, (480, 320))
            img         = Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
            self._photo = ctk.CTkImage(light_image=img, dark_image=img, size=(480, 320))
            self.cam_label.configure(image=self._photo)

        if self._running:
            self.after(33, self._feed_loop)   # ~30 fps

    def _set_collecting(self, kind: str):
        if kind == 'good' and self._good_count < FRAMES_NEEDED:
            self._collecting = 'good'
            self.status_lbl.configure(
                text="⏺  Capturing Good Posture…  Sit tall and stay still!")
        elif kind == 'bad' and self._bad_count < FRAMES_NEEDED:
            self._collecting = 'bad'
            self.status_lbl.configure(
                text="⏺  Capturing Bad Posture…  Slouch naturally!")

    def _stop_collecting(self):
        self._collecting = None
        self._update_status()

    def _update_status(self):
        g_done = self._good_count >= FRAMES_NEEDED
        b_done = self._bad_count  >= FRAMES_NEEDED
        if g_done and b_done:
            self.status_lbl.configure(text="Both classes captured ✓  Building model…")
        elif g_done:
            self.status_lbl.configure(text="Good ✓  ·  Now hold B for Bad Posture")
        elif b_done:
            self.status_lbl.configure(text="Bad ✓  ·  Now hold G for Good Posture")
        else:
            self.status_lbl.configure(text="Hold G (Good Posture) or B (Bad Posture)")

    # ── Step 3 — Train ────────────────────────────────────────────────────────

    def _build_step3(self):
        self._clear()
        self._header("Training Your Model")

        self.train_lbl = ctk.CTkLabel(
            self, text="Saving dataset…",
            font=FONT_BODY, text_color=ACCENT_PRIMARY)
        self.train_lbl.pack(pady=24)

        self.train_prog = ctk.CTkProgressBar(
            self, width=360,
            fg_color=BG_SECONDARY, progress_color=ACCENT_PRIMARY)
        self.train_prog.set(0)
        self.train_prog.pack(pady=10)

        threading.Thread(target=self._train_model, daemon=True).start()

    def _train_model(self):
        def _status(msg, pct):
            self.after(0, lambda: self.train_lbl.configure(text=msg))
            self.after(0, lambda: self.train_prog.set(pct))

        try:
            # 1 — Save CSV
            _status("Saving calibration_dataset.csv…", 0.15)
            with open(DATASET_PATH, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'neck_angle', 'shoulder_tilt',
                    'triangle_area', 'ear_dist', 'label',
                ])
                for feats, label in self._dataset:
                    writer.writerow([*feats.tolist(), label])

            # 2 — Feature matrix
            _status("Building feature matrix…", 0.35)
            X = np.array([f for f, _ in self._dataset], dtype=np.float32)
            y = np.array([l for _, l in self._dataset])

            # 3 — RandomForest
            _status("Training RandomForestClassifier (100 trees)…", 0.55)
            from sklearn.ensemble import RandomForestClassifier
            import pickle as pkl
            model = RandomForestClassifier(
                n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
            model.fit(X, y)

            # 4 — Save model
            _status("Saving posture_model.pkl…", 0.80)
            with open(MODEL_PATH, 'wb') as f:
                pkl.dump(model, f)

            # 5 — Calibration profile
            good_feats = [f for f, l in self._dataset if l == 'good']
            profile = {
                'neck_angle':    round(float(np.mean([f[0] for f in good_feats])), 1),
                'shoulder_tilt': round(float(np.mean([f[1] for f in good_feats])), 1),
                'samples_good':  self._good_count,
                'samples_bad':   self._bad_count,
                'model':         'RandomForestClassifier',
                'pose_backend':  'yolov8n-pose',
            }
            with open(CALIBRATION_PATH, 'w') as f:
                json.dump(profile, f, indent=2)

            _status("Complete!", 1.0)
            self.after(400, lambda: self._show_complete(profile))

        except Exception as exc:
            self.after(0, lambda: self.train_lbl.configure(
                text=f"Training error: {exc}\nSaving rule-based fallback…"
            ))
            with open(CALIBRATION_PATH, 'w') as f:
                json.dump({'neck_angle': 12.0, 'shoulder_tilt': 0.5,
                           'samples': 0, 'fallback': True}, f)
            self.after(1800, self._finish)

    # ── Step 3 confirmation ───────────────────────────────────────────────────

    def _show_complete(self, profile: dict):
        self._clear()

        ctk.CTkLabel(
            self, text="Model Trained ✓",
            font=FONT_DISPLAY, text_color=ACCENT_PRIMARY,
        ).pack(pady=(50, 16))

        card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=14)
        card.pack(padx=80, pady=8, fill="x")

        rows = [
            ("Good posture frames",  str(self._good_count)),
            ("Bad posture frames",   str(self._bad_count)),
            ("Model",                "RandomForestClassifier · 100 trees"),
            ("Pose backend",         "YOLOv8n-pose (ultralytics)"),
            ("Baseline neck angle",  f"{profile.get('neck_angle', '—')}°"),
            ("Dataset saved",        "calibration_dataset.csv"),
        ]
        for label, value in rows:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(row, text=label, font=FONT_BODY,
                         text_color=TEXT_SECONDARY).pack(side="left")
            ctk.CTkLabel(row, text=value, font=FONT_BODY,
                         text_color=ACCENT_PRIMARY).pack(side="right")

        ctk.CTkButton(
            self, text="Start Monitoring →",
            font=FONT_HEADING,
            fg_color=ACCENT_PRIMARY, text_color=BG_PRIMARY,
            hover_color="#00cc55", width=240, height=48, corner_radius=24,
            command=self._finish,
        ).pack(pady=28)

    # ── Mock calibration (no camera / no YOLO) ───────────────────────────────

    def _mock_calibration(self):
        with open(CALIBRATION_PATH, 'w') as f:
            json.dump({'neck_angle': 12.0, 'shoulder_tilt': 0.5,
                       'samples': 0, 'mock': True}, f)
        self._clear()
        ctk.CTkLabel(
            self, text="Mock Calibration ✓",
            font=FONT_DISPLAY, text_color=ACCENT_PRIMARY,
        ).pack(pady=(100, 16))
        ctk.CTkLabel(
            self,
            text="Camera or YOLO unavailable — rule-based detection will be used.",
            font=FONT_BODY, text_color=TEXT_SECONDARY,
        ).pack()
        ctk.CTkButton(
            self, text="Start Monitoring →",
            font=FONT_HEADING,
            fg_color=ACCENT_PRIMARY, text_color=BG_PRIMARY,
            hover_color="#00cc55", width=240, height=48, corner_radius=24,
            command=self._finish,
        ).pack(pady=28)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _finish(self):
        self._running = False
        if self._cap and self._cap.isOpened():
            self._cap.release()
        # YOLO model has no explicit close(); GC handles it
        self._yolo = None
        self.destroy()
        if self.on_complete:
            self.on_complete()

    def destroy(self):
        self._running = False
        try:
            super().destroy()
        except Exception:
            pass
