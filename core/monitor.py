# core/monitor.py
import logging
import threading
import time
import queue
from typing import Callable, Optional

try:
    import cv2
    import numpy as np
    _CV2 = True
except ImportError:
    _CV2 = False

from core.camera import open_webcam

log = logging.getLogger(__name__)

DB_FLUSH_INTERVAL = 5 * 60   # seconds between average-score DB commits

# Read-failure tuning
_REOPEN_AFTER   = 10   # consecutive failures → release + reopen capture
_GIVE_UP_AFTER  = 30   # consecutive failures → set camera_status=FAILED, cap=None
_FAIL_SLEEP_SEC = 1.0  # backoff sleep while in error state


class MonitoringThread(threading.Thread):
    """
    Background thread: 2-fps webcam capture → PostureEngine → queues.

    Public attributes (read from UI thread for LiveViewWindow):
        latest_annotated  — BGR numpy frame with skeleton drawn
        latest_score      — most recent posture score (0-100)
        latest_label      — 'Good' | 'Slouch' | 'Forward Head'
        latest_neck       — neck angle in degrees
        latest_sh_tilt    — shoulder tilt value
        latest_blink      — blink rate per minute
    """

    FRAME_INTERVAL = 0.5   # 2 fps

    def __init__(
        self,
        posture_queue: queue.Queue,
        eye_queue: queue.Queue,
        activity_detector,
        session_ticker_callback: Optional[Callable] = None,
        db_flush_callback: Optional[Callable] = None,
    ):
        """
        db_flush_callback(avg_score, avg_label, session_id)
            Called every DB_FLUSH_INTERVAL seconds with the period average.
        """
        super().__init__(daemon=True, name="SpineAI-Monitor")
        self.posture_queue      = posture_queue
        self.eye_queue          = eye_queue
        self.activity_detector  = activity_detector
        self.session_ticker_cb  = session_ticker_callback
        self.db_flush_cb        = db_flush_callback

        self._running = False
        self._paused  = False
        self._lock    = threading.Lock()

        # Shared state for LiveViewWindow
        self.latest_annotated: Optional['np.ndarray'] = None
        self.latest_score:     float = 0.0
        self.latest_label:     str   = '—'
        self.latest_neck:      float = 0.0
        self.latest_sh_tilt:   float = 0.0
        self.latest_blink:     float = 15.0
        self.latest_triangle:  float = 0.0

        # Camera health — read by UI thread to surface reconnect / error states
        self.camera_status: str = "OK"   # "OK" | "RECONNECTING" | "FAILED"
        self._consec_fail:  int = 0

        # Screen distance (cm) sampled from PostureEngine — UI reads for Eye Health tab
        self.latest_distance_cm: float = 0.0

        # 5-minute rolling score buffer for DB flush
        self._score_buffer:    list[float] = []
        self._label_buffer:    list[str]   = []
        self._flush_timer:     float       = 0.0

        # Exposed so app.py can call engine.reload_model() / set_sensitivity()
        self.engine = None

    # ── Control ───────────────────────────────────────────────────────────────

    def stop(self):
        with self._lock:
            self._running = False

    def pause(self):
        with self._lock:
            self._paused = True

    def resume(self):
        with self._lock:
            self._paused = False

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        from core.posture_engine import PostureEngine

        self._running  = True
        engine         = PostureEngine()
        self.engine    = engine          # expose for hot-swap / sensitivity
        last_tick      = time.time()
        self._flush_timer = time.time()

        cap = open_webcam(0) if _CV2 else None
        if cap is None:
            self.camera_status = "FAILED"

        while self._running:
            with self._lock:
                paused = self._paused

            now = time.time()

            # ── Per-second session ticker ────────────────────────────────────
            if now - last_tick >= 1.0 and self.session_ticker_cb:
                active = self.activity_detector.is_active()
                self.session_ticker_cb(active)
                last_tick = now

            # ── 5-minute DB flush ────────────────────────────────────────────
            if now - self._flush_timer >= DB_FLUSH_INTERVAL:
                self._flush_timer = now
                if self._score_buffer and self.db_flush_cb:
                    avg_score = sum(self._score_buffer) / len(self._score_buffer)
                    # majority-vote label
                    from collections import Counter
                    avg_label = Counter(self._label_buffer).most_common(1)[0][0]
                    try:
                        self.db_flush_cb(avg_score, avg_label)
                    except Exception:
                        pass
                self._score_buffer.clear()
                self._label_buffer.clear()

            if paused or cap is None:
                time.sleep(self.FRAME_INTERVAL)
                continue

            if not self.activity_detector.is_active():
                time.sleep(self.FRAME_INTERVAL)
                continue

            ret, frame = cap.read()
            if not ret:
                self._consec_fail += 1
                if self._consec_fail == 1:
                    log.warning("Camera read failed; entering reconnect mode.")
                    self.camera_status = "RECONNECTING"
                if self._consec_fail == _REOPEN_AFTER:
                    log.warning(
                        "Camera still failing after %d reads — reopening.",
                        _REOPEN_AFTER,
                    )
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = open_webcam(0)
                if self._consec_fail >= _GIVE_UP_AFTER:
                    log.error(
                        "Camera unrecoverable after %d failed reads — giving up.",
                        _GIVE_UP_AFTER,
                    )
                    self.camera_status = "FAILED"
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
                        cap = None
                time.sleep(_FAIL_SLEEP_SEC)
                continue

            if self._consec_fail:
                self._consec_fail = 0
                self.camera_status = "OK"

            try:
                posture, eye = engine.process(frame)

                # Update shared state (read by LiveViewWindow at 10 fps)
                self.latest_annotated = posture.frame_annotated
                self.latest_score     = posture.score
                self.latest_label     = posture.label
                self.latest_neck      = posture.neck_angle
                self.latest_sh_tilt   = posture.shoulder_tilt
                self.latest_triangle  = posture.triangle_area
                self.latest_blink     = eye.blink_rate
                self.latest_distance_cm = eye.screen_distance_cm

                # Buffer for 5-min flush
                self._score_buffer.append(posture.score)
                self._label_buffer.append(posture.label)

                # Push to UI queues (non-blocking)
                if not self.posture_queue.full():
                    self.posture_queue.put_nowait(posture)
                if not self.eye_queue.full():
                    self.eye_queue.put_nowait(eye)

            except Exception:
                pass

            time.sleep(self.FRAME_INTERVAL)

        if cap and cap.isOpened():
            cap.release()
        engine.release()
