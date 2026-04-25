# app.py
import sys
import os
import json
import queue
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk
from config import *

from components.sidebar            import ProfileSidebar
from components.notification_popup import NotificationPopup
from tabs.dashboard_tab            import DashboardTab
from tabs.spine_health_tab         import SpineHealthTab
from tabs.eye_health_tab           import EyeHealthTab
from tabs.sitting_time_tab         import SittingTimeTab


class SpineAIApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1280x780")
        self.root.minsize(960, 640)
        self.root.overrideredirect(True)
        self.root.configure(fg_color=BG_PRIMARY)
        self.root.deiconify()

        # Live-data queues
        self.posture_queue = queue.Queue(maxsize=20)
        self.eye_queue     = queue.Queue(maxsize=20)

        self._last_label   = 'unknown'
        self._last_score   = 0.0
        self._db_tick      = 0
        self._session_id   = None
        self._monitoring   = False

        # 20-20-20 tracking
        self._20_elapsed   = 0   # seconds since last 20-20-20 reset
        # 40-min eye-activity tracking (survives tab reconstruction)
        self._40_elapsed   = 0
        self._40_target    = 40 * 60

        # Core modules (wired in start_monitoring)
        self.activity_detector = None
        self.session_tracker   = None
        self.alert_manager     = None
        self.monitor_thread    = None

        self._current_tab_view = None
        self._current_tab_name = None

        self._setup_ui()

    # =========================================================================
    # UI Construction
    # =========================================================================

    def _setup_ui(self):
        self._build_top_bar()
        self._build_tab_bar()
        self._build_content()
        self._build_sidebar()
        self._start_clock()
        self.switch_tab("Dashboard")

    def _build_top_bar(self):
        self.top_bar = ctk.CTkFrame(
            self.root, height=60,
            fg_color=BG_SECONDARY, corner_radius=0
        )
        self.top_bar.pack(side="top", fill="x")
        self.top_bar.pack_propagate(False)
        self.top_bar.bind("<B1-Motion>", self._move_window)
        self.top_bar.bind("<Button-1>",  self._get_pos)

        logo = ctk.CTkLabel(
            self.top_bar, text="⬡  SPINE AI",
            font=FONT_HEADING, text_color=ACCENT_PRIMARY
        )
        logo.pack(side="left", padx=20)
        logo.bind("<B1-Motion>", self._move_window)
        logo.bind("<Button-1>",  self._get_pos)

        # Window controls
        ctk.CTkButton(
            self.top_bar, text="✕", width=40, height=40,
            fg_color="transparent", text_color=TEXT_SECONDARY,
            hover_color=ACCENT_RED, font=FONT_HEADING,
            command=self._on_close
        ).pack(side="right", padx=(0, 10))

        ctk.CTkButton(
            self.top_bar, text="–", width=40, height=40,
            fg_color="transparent", text_color=TEXT_SECONDARY,
            hover_color=BG_CARD_HOVER, font=FONT_HEADING,
            command=self._minimise
        ).pack(side="right")

        ctk.CTkButton(
            self.top_bar, text="👤  Profile ▾", width=120,
            fg_color="transparent", hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRIMARY, font=FONT_BODY,
            command=self.toggle_sidebar
        ).pack(side="right", padx=10)

        # ── Recalibrate button (next to monitoring status) ────────────────────
        self.recalibrate_btn = ctk.CTkButton(
            self.top_bar, text="⚙ Recalibrate", width=110, height=30,
            fg_color=BG_CARD, text_color=TEXT_SECONDARY,
            hover_color=BG_CARD_HOVER, font=FONT_SMALL,
            corner_radius=15, command=self._recalibrate
        )
        self.recalibrate_btn.pack(side="right", padx=(0, 6))

        # Clock
        self.clock_lbl = ctk.CTkLabel(
            self.top_bar, text="",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, cursor="hand2",
        )
        self.clock_lbl.pack(side="right", padx=(0, 14))
        self.clock_lbl.bind("<Button-1>", lambda _: self._open_live_view())

        # Status dot + label
        self.status_dot = ctk.CTkLabel(
            self.top_bar, text="●",
            font=("Segoe UI", 14), text_color=TEXT_SECONDARY
        )
        self.status_dot.pack(side="right", padx=(0, 4))

        self.status_lbl = ctk.CTkLabel(
            self.top_bar, text="IDLE",
            font=FONT_SMALL, text_color=TEXT_SECONDARY
        )
        self.status_lbl.pack(side="right", padx=(0, 6))

    def _build_tab_bar(self):
        self.tab_frame = ctk.CTkFrame(
            self.root, fg_color="transparent", corner_radius=0
        )
        self.tab_frame.pack(side="top", fill="x", pady=(14, 4), padx=20)

        self._tabs_list = ["Dashboard", "Spine Health", "Eye Health", "Sitting Time"]
        self._tab_btns  = {}
        for text in self._tabs_list:
            btn = ctk.CTkButton(
                self.tab_frame, text=text,
                font=FONT_BODY, width=130, height=36, corner_radius=18,
                command=lambda t=text: self.switch_tab(t)
            )
            btn.pack(side="left", padx=(0, 10))
            self._tab_btns[text] = btn

    def _build_content(self):
        self.content_frame = ctk.CTkFrame(
            self.root, fg_color="transparent"
        )
        self.content_frame.pack(fill="both", expand=True, padx=20, pady=10)

    def _build_sidebar(self):
        self.sidebar_open = False
        self.sidebar      = ProfileSidebar(self.root, self)

    # =========================================================================
    # Window chrome
    # =========================================================================

    def _get_pos(self, event):
        self.x_off = event.x
        self.y_off = event.y

    def _move_window(self, event):
        self.root.geometry(
            f"+{event.x_root - self.x_off}+{event.y_root - self.y_off}"
        )

    def _minimise(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.bind("<Map>", self._on_restore)

    def _on_restore(self, _event):
        self.root.overrideredirect(True)
        self.root.unbind("<Map>")

    def _on_close(self):
        if self.monitor_thread:
            self.monitor_thread.stop()
        if self.activity_detector:
            self.activity_detector.stop()
        if self._session_id and self.session_tracker:
            try:
                from database.db_manager import db
                db.update_session(self._session_id, self.session_tracker.get_stats())
            except Exception:
                pass
        self.root.quit()

    # =========================================================================
    # Recalibrate
    # =========================================================================

    def _recalibrate(self):
        """Wipe calibration_profile.json and relaunch the Calibration Wizard."""
        # Stop monitoring while we recalibrate
        was_monitoring = self._monitoring
        if self.monitor_thread:
            self.monitor_thread.pause()
        self._monitoring = False
        self.status_lbl.configure(text="RECALIBRATING", text_color="#ffaa00")
        self.status_dot.configure(text_color="#ffaa00")

        # Wipe existing calibration files
        import glob as _glob
        for path in [
            os.path.join(BASE_DIR, "calibration_profile.json"),
            os.path.join(BASE_DIR, "posture_model.pkl"),
            os.path.join(BASE_DIR, "posture_knn.pkl"),
        ]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

        def _on_complete():
            # Hot-swap the new model into the monitor thread's engine
            if self.monitor_thread and hasattr(self.monitor_thread, 'engine'):
                self.monitor_thread.engine.reload_model()
            # Resume monitoring
            if was_monitoring and self.monitor_thread:
                self.monitor_thread.resume()
                self._monitoring = True
                self.status_lbl.configure(text="MONITORING", text_color=ACCENT_PRIMARY)
                self._pulse_dot()
            else:
                self.status_lbl.configure(text="IDLE", text_color=TEXT_SECONDARY)
                self.status_dot.configure(text_color=TEXT_SECONDARY)

        from core.calibration import CalibrationWizard
        CalibrationWizard(self.root, on_complete=_on_complete)

    # =========================================================================
    # Clock + status pulse
    # =========================================================================

    def _start_clock(self):
        self._tick_clock()

    def _tick_clock(self):
        self.clock_lbl.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    _PULSE = [ACCENT_PRIMARY, "#007733"]

    def _pulse_dot(self, idx: int = 0):
        if not self._monitoring:
            return

        # Surface camera health from the monitor thread
        cam_status = getattr(self.monitor_thread, "camera_status", "OK")
        if cam_status == "RECONNECTING":
            self.status_lbl.configure(text="CAMERA…", text_color="#ffaa00")
            self.status_dot.configure(text_color="#ffaa00")
            self.root.after(800, lambda: self._pulse_dot(idx + 1))
            return
        if cam_status == "FAILED":
            self.status_lbl.configure(text="CAMERA ERROR", text_color="#ff4444")
            self.status_dot.configure(text_color="#ff4444")
            self.root.after(800, lambda: self._pulse_dot(idx + 1))
            return
        if self.status_lbl.cget("text") in ("CAMERA…", "CAMERA ERROR"):
            self.status_lbl.configure(text="MONITORING", text_color=ACCENT_PRIMARY)

        self.status_dot.configure(text_color=self._PULSE[idx % 2])
        self.root.after(800, lambda: self._pulse_dot(idx + 1))

    # =========================================================================
    # Tab switching
    # =========================================================================

    def switch_tab(self, tab_name: str):
        for name, btn in self._tab_btns.items():
            if name == tab_name:
                btn.configure(fg_color=ACCENT_PRIMARY,
                              text_color=BG_PRIMARY,
                              hover_color=ACCENT_PRIMARY)
            else:
                btn.configure(fg_color=BG_CARD,
                              text_color=TEXT_SECONDARY,
                              hover_color=BG_CARD_HOVER)

        for w in self.content_frame.winfo_children():
            w.destroy()

        self._current_tab_name = tab_name

        # Pass app_ref for live updates where supported
        tab_map = {
            "Dashboard":    lambda p: DashboardTab(p, app_ref=self),
            "Spine Health": lambda p: SpineHealthTab(p, app_ref=self),
            "Eye Health":   lambda p: EyeHealthTab(p, app_ref=self),
            "Sitting Time": lambda p: SittingTimeTab(p, app_ref=self),
        }
        view = tab_map[tab_name](self.content_frame)
        view.pack(fill="both", expand=True)
        self._current_tab_view = view

    # =========================================================================
    # Sidebar
    # =========================================================================

    def toggle_sidebar(self):
        if not self.sidebar_open:
            self.sidebar.place(relx=1.0, x=-300, y=60, relheight=1.0)
            self.sidebar_open = True
        else:
            self.sidebar.place_forget()
            self.sidebar_open = False

    # =========================================================================
    # Monitoring startup
    # =========================================================================

    def start_monitoring(self):
        from core.activity_detector import ActivityDetector
        from core.session_tracker   import SessionTracker
        from core.alert_manager     import AlertManager
        from core.monitor           import MonitoringThread
        from database.db_manager    import db

        self._session_id = db.start_session()

        self.activity_detector = ActivityDetector()
        self.activity_detector.start()

        self.alert_manager = AlertManager(popup_callback=self._schedule_popup)

        self.session_tracker = SessionTracker(
            on_break_needed=self.alert_manager.trigger_break_alert,
            on_good_streak=self.alert_manager.trigger_good_streak,
        )

        def _ticker(is_active: bool):
            if self.session_tracker:
                self.session_tracker.tick(
                    is_active, self._last_label, self._last_score
                )

        def _db_flush(avg_score: float, avg_label: str):
            self.root.after(0, lambda: self._commit_posture_record(avg_score, avg_label))

        self.monitor_thread = MonitoringThread(
            posture_queue=self.posture_queue,
            eye_queue=self.eye_queue,
            activity_detector=self.activity_detector,
            session_ticker_callback=_ticker,
            db_flush_callback=_db_flush,
        )
        self.monitor_thread.start()

        self._monitoring = True
        self.status_lbl.configure(text="MONITORING", text_color=ACCENT_PRIMARY)
        self._pulse_dot()
        self.root.after(1000, self._poll)

    def toggle_monitoring(self):
        if not self.monitor_thread:
            return
        if self.monitor_thread.is_paused:
            self.monitor_thread.resume()
            self._monitoring = True
            self.status_lbl.configure(text="MONITORING", text_color=ACCENT_PRIMARY)
            self._pulse_dot()
        else:
            self.monitor_thread.pause()
            self._monitoring = False
            self.status_lbl.configure(text="PAUSED", text_color=TEXT_SECONDARY)
            self.status_dot.configure(text_color=TEXT_SECONDARY)

    # =========================================================================
    # Queue polling (UI thread via after())
    # =========================================================================

    def _poll(self):
        while not self.posture_queue.empty():
            try:
                self._on_posture(self.posture_queue.get_nowait())
            except queue.Empty:
                break

        while not self.eye_queue.empty():
            try:
                self._on_eye(self.eye_queue.get_nowait())
            except queue.Empty:
                break

        # Flush session stats to DB every 60 s
        self._db_tick += 1
        if self._db_tick >= 60 and self._session_id and self.session_tracker:
            self._db_tick = 0
            self._flush_db()

        # Advance 20-20-20 timer
        self._20_elapsed += 1
        if self._20_elapsed >= 20 * 60:
            self._20_elapsed = 0
            if self.alert_manager:
                self.alert_manager.trigger_20_20_20()
        if self._current_tab_name == "Eye Health" and \
                isinstance(self._current_tab_view, EyeHealthTab):
            try:
                self._current_tab_view.update_2020_timer(self._20_elapsed)
            except Exception:
                pass

        # Phase 5 — live refresh of tabs from SessionTracker / MonitoringThread
        is_active = (
            self.activity_detector.is_active()
            if self.activity_detector else False
        )

        # Advance 40-min eye-activity timer (state lives on app — survives tab
        # reconstruction). Fire popup once per cycle, then reset.
        if is_active:
            self._40_elapsed += 1
        if self._40_elapsed >= self._40_target:
            self._40_elapsed = 0
            try:
                from components.notification_popup import NotificationPopup
                NotificationPopup(
                    title="Eye Break",
                    message="40 Minutes Active: Please look 20 feet away for 20 seconds.",
                    alert_type="warning",
                )
            except Exception:
                pass

        view = self._current_tab_view
        try:
            if isinstance(view, EyeHealthTab):
                view.tick_active(is_active)
            elif isinstance(view, SpineHealthTab):
                view.refresh()
            elif isinstance(view, SittingTimeTab):
                view.refresh()
        except Exception:
            pass

        self.root.after(1000, self._poll)

    # ── Posture update ────────────────────────────────────────────────────────

    def _on_posture(self, frame):
        self._last_label = frame.label
        self._last_score = frame.score

        # Status dot colour
        if self._monitoring:
            self.status_dot.configure(
                text_color=ACCENT_PRIMARY
                if frame.label.lower() == 'good' else ACCENT_RED
            )

        if self.alert_manager:
            self.alert_manager.check_posture(frame.label)

        # Dashboard live push
        self._push_dashboard(frame)

        # Sidebar score
        try:
            self.sidebar.update_score(int(frame.score))
        except Exception:
            pass

    # ── Eye update ────────────────────────────────────────────────────────────

    def _on_eye(self, eye):
        # Eye Health tab live update
        if self._current_tab_name == "Eye Health" and \
                isinstance(self._current_tab_view, EyeHealthTab):
            try:
                self._current_tab_view.update_blink(
                    eye.blink_rate,
                    eye.screen_distance_cm,
                    None,   # strain computed inside the tab (Phase 5 formula)
                )
            except Exception:
                pass

        # DB persist
        if self._session_id:
            try:
                from database.db_manager import db
                db.save_eye_record(
                    self._session_id, eye.timestamp,
                    eye.blink_rate, eye.screen_distance_cm, eye.strain_score
                )
            except Exception:
                pass

    # ── Dashboard live push ───────────────────────────────────────────────────

    def _push_dashboard(self, frame):
        if self._current_tab_name != "Dashboard" or \
                not isinstance(self._current_tab_view, DashboardTab):
            return
        view = self._current_tab_view
        try:
            stats = self.session_tracker.get_stats() \
                if self.session_tracker else None
            view.push_posture(frame.label, frame.score, stats)
            # Spine model segment highlight
            view.update_slouch_type(getattr(frame, 'slouch_type', ''))
            # Recovery timer
            view.update_recovery_timer(frame.label)
        except Exception:
            pass

    # ── Live view ─────────────────────────────────────────────────────────────

    def _open_live_view(self):
        if not self.monitor_thread:
            return
        if hasattr(self, '_live_view') and self._live_view and \
                self._live_view.winfo_exists():
            self._live_view.lift()
            return
        from components.live_view import LiveViewWindow
        self._live_view = LiveViewWindow(self.root, self.monitor_thread)

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _commit_posture_record(self, avg_score: float, avg_label: str):
        if not self._session_id:
            return
        try:
            from database.db_manager import db
            db.save_posture_record(
                self._session_id,
                datetime.now().isoformat(),
                round(avg_score, 1),
                avg_label,
                neck_angle=0.0,
                shoulder_tilt=0.0,
            )
        except Exception:
            pass

    def _flush_db(self):
        try:
            from database.db_manager import db
            db.update_session(self._session_id, self.session_tracker.get_stats())
        except Exception:
            pass

    # ── Popup (thread-safe) ───────────────────────────────────────────────────

    def _schedule_popup(self, alert_type: str, title: str, message: str):
        self.root.after(0, lambda: self._show_popup(alert_type, title, message))

    def _show_popup(self, alert_type: str, title: str, message: str):
        kind = 'danger' if alert_type in ('danger', 'posture') else 'warning'
        try:
            NotificationPopup(title=title, message=message, alert_type=kind)
        except Exception:
            pass
