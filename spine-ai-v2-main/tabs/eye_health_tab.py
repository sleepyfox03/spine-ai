# tabs/eye_health_tab.py
# Eye Health tab — live BPM, 20-20-20 timer, screen distance, strain score
import customtkinter as ctk
import tkinter as tk
from config import *
from components.ring_chart import RingChart
from components.notification_popup import NotificationPopup


class EyeHealthTab(ctk.CTkScrollableFrame):
    """
    Live-updating Eye Health panel.

    Public API (called from app.py on every eye-queue poll):
        update_blink(bpm, dist_cm, strain=None)  — strain auto-computed if None
        tick_active(is_active)                   — advances the 40-min eye-activity timer
        update_2020_timer(elapsed_sec)           — advances the 20-min 20-20-20 ring
    """

    # BPM threshold below which the "Remember to Blink" warning activates
    STARE_THRESHOLD = 10.0

    def __init__(self, parent, app_ref=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._app = app_ref
        self._last_bpm = 15.0

        # 40-min eye-activity countdown (independent of the 20-20-20 ring above)
        self._40_elapsed = 0
        self._40_target  = 40 * 60

        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure((0, 1), weight=1)

        # ── A: Blink Rate Monitor ─────────────────────────────────────────────
        self.blink_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.blink_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            self.blink_frame, text="Real-Time Blink Rate",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(pady=(20, 5))

        # BPM big number
        self.lbl_blink_val = ctk.CTkLabel(
            self.blink_frame, text="–",
            font=("Segoe UI", 52, "bold"), text_color=ACCENT_RED
        )
        self.lbl_blink_val.pack()

        ctk.CTkLabel(
            self.blink_frame, text="blinks / min (BPM)",
            font=FONT_BODY, text_color=TEXT_SECONDARY
        ).pack()

        # Status / stare warning
        self.lbl_blink_status = ctk.CTkLabel(
            self.blink_frame, text="Waiting for camera…",
            font=FONT_HEADING, text_color=TEXT_SECONDARY
        )
        self.lbl_blink_status.pack(pady=(12, 4))

        # "Remember to Blink" toast label (hidden until BPM < threshold)
        self.lbl_stare_toast = ctk.CTkLabel(
            self.blink_frame,
            text="👁  Remember to Blink!",
            font=("Segoe UI", 15, "bold"),
            text_color=ACCENT_RED,
            fg_color="#1a0a0a",
            corner_radius=8,
        )
        # Don't pack yet — will appear when BPM < 10

        # BPM progress bar (0–30 range)
        self.bpm_bar = ctk.CTkProgressBar(
            self.blink_frame, width=220, height=10,
            fg_color=BG_SECONDARY, progress_color=ACCENT_RED
        )
        self.bpm_bar.set(0)
        self.bpm_bar.pack(pady=(4, 6))

        # Range labels
        rng = ctk.CTkFrame(self.blink_frame, fg_color="transparent")
        rng.pack()
        ctk.CTkLabel(rng, text="0", font=FONT_SMALL,
                     text_color=TEXT_SECONDARY).pack(side="left", padx=(22, 0))
        ctk.CTkLabel(rng, text="Normal: 12–20 BPM", font=FONT_SMALL,
                     text_color=TEXT_SECONDARY).pack(side="left", expand=True)
        ctk.CTkLabel(rng, text="30", font=FONT_SMALL,
                     text_color=TEXT_SECONDARY).pack(side="right", padx=(0, 22))

        ctk.CTkFrame(self.blink_frame, height=1,
                     fg_color=BG_SECONDARY).pack(fill="x", padx=20, pady=12)
        ctk.CTkLabel(
            self.blink_frame,
            text="Measured via Eye Aspect Ratio\n(MediaPipe Face Mesh landmarks 159/145, 33/133)",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, justify="center"
        ).pack(pady=(0, 20))

        # ── B: 20-20-20 Rule Timer ────────────────────────────────────────────
        self.timer_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.timer_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            self.timer_frame, text="20-20-20 Timer",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(pady=(20, 5))

        self.timer_ring = RingChart(
            self.timer_frame, size=140, thickness=12,
            color=ACCENT_PRIMARY, bg_color=BG_CARD
        )
        self.timer_ring.pack(pady=10)
        self.timer_ring.set_progress(0)

        self.timer_lbl = ctk.CTkLabel(
            self.timer_frame, text="00:00 of 20 min",
            font=FONT_BODY, text_color=TEXT_SECONDARY
        )
        self.timer_lbl.pack(pady=(0, 10))

        ctk.CTkLabel(
            self.timer_frame,
            text="Every 20 min: look at something\n20 feet away for 20 seconds.",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, justify="center"
        ).pack(pady=(0, 12))

        # 40-minute eye-activity countdown (independent of the 20-20-20 ring)
        ctk.CTkFrame(self.timer_frame, height=1,
                     fg_color=BG_SECONDARY).pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(
            self.timer_frame, text="NEXT EYE BREAK IN",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).pack()
        self.lbl_40_countdown = ctk.CTkLabel(
            self.timer_frame, text="40:00",
            font=("Segoe UI", 22, "bold"), text_color=ACCENT_PRIMARY,
        )
        self.lbl_40_countdown.pack(pady=(2, 20))

        # ── C: Screen Distance ────────────────────────────────────────────────
        self.dist_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.dist_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            self.dist_frame, text="Screen Distance",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(pady=(20, 5))

        self.lbl_dist_val = ctk.CTkLabel(
            self.dist_frame, text="– cm",
            font=("Segoe UI", 36, "bold"), text_color="#ffaa00"
        )
        self.lbl_dist_val.pack(pady=10)

        self.dist_bar = ctk.CTkProgressBar(
            self.dist_frame, width=200, height=10,
            fg_color=BG_SECONDARY, progress_color="#ffaa00"
        )
        self.dist_bar.set(0)
        self.dist_bar.pack(pady=6)

        ctk.CTkLabel(
            self.dist_frame,
            text="Ideal distance: 50–70 cm\n(estimated from face mesh IPD)",
            font=FONT_SMALL, text_color=TEXT_SECONDARY, justify="center"
        ).pack(pady=(0, 20))

        # ── D: Eye Strain Score ───────────────────────────────────────────────
        self.strain_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.strain_frame.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

        ctk.CTkLabel(
            self.strain_frame, text="Overall Eye Strain",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(pady=(20, 5))

        self.strain_ring = RingChart(
            self.strain_frame, size=120, thickness=10,
            color="#ffaa00", bg_color=BG_CARD
        )
        self.strain_ring.pack(pady=10)
        self.strain_ring.set_progress(0)

        self.strain_lbl = ctk.CTkLabel(
            self.strain_frame, text="No data yet",
            font=FONT_HEADING, text_color=TEXT_SECONDARY
        )
        self.strain_lbl.pack(pady=(5, 20))

        # ── E: Blue Light Info ────────────────────────────────────────────────
        self.blue_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.blue_frame.grid(
            row=2, column=0, columnspan=2,
            padx=10, pady=10, sticky="nsew"
        )

        ctk.CTkLabel(
            self.blue_frame, text="Blue Light Exposure Tips",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=20, pady=(20, 5))

        info_text = (
            "🔵 Blue light from screens suppresses melatonin and disrupts sleep rhythms.\n\n"
            "💡 Enable Night Mode after 6 PM, or use blue-light filtering glasses.\n\n"
            "👁  Low blink rate (< 10 BPM) accelerates dry-eye syndrome and digital eye strain."
        )
        ctk.CTkLabel(
            self.blue_frame, text=info_text,
            font=FONT_BODY, text_color=TEXT_SECONDARY,
            justify="left", wraplength=640
        ).pack(anchor="w", padx=20, pady=(0, 20))

    # ── Live update API ───────────────────────────────────────────────────────

    def update_blink(self, bpm: float, dist_cm: float, strain: float | None = None):
        """
        Push live eye data into the tab.  Called from app.py every polling tick.
        Also fires the 'Remember to Blink' stare warning if BPM < 10.
        If `strain` is None, it is computed from `bpm` and `dist_cm`.
        """
        self._last_bpm = bpm

        if strain is None:
            strain = max(0, min(100,
                round(max(0, (15 - bpm) * 5) + max(0, (50 - dist_cm) * 1.2))
            ))

        # BPM display
        bpm_int = int(round(bpm))
        self.lbl_blink_val.configure(text=str(bpm_int))

        # Colour coding
        if bpm < self.STARE_THRESHOLD:
            color = ACCENT_RED
            status = "You're staring 👁  — blink now!"
            self._show_stare_toast()
            # Fire alert manager (with cooldown handled there)
            if self._app and hasattr(self._app, 'alert_manager') \
                    and self._app.alert_manager:
                self._app.alert_manager.trigger_stare_warning()
        elif bpm < 12:
            color = "#ffaa00"
            status = "Low blink rate — try to blink more."
            self._hide_stare_toast()
        elif bpm <= 20:
            color = ACCENT_PRIMARY
            status = "Healthy blink rate 🟢"
            self._hide_stare_toast()
        else:
            color = "#4fc3f7"
            status = "High blink rate (normal under fatigue)"
            self._hide_stare_toast()

        self.lbl_blink_val.configure(text_color=color)
        self.lbl_blink_status.configure(text=status, text_color=color)
        self.bpm_bar.set(min(1.0, bpm / 30.0))
        self.bpm_bar.configure(progress_color=color)

        # Screen distance display — range labels per Phase 5 spec
        if dist_cm >= 70:
            d_label = "TOO FAR"
            dist_color = "#ffaa00"
        elif dist_cm >= 55:
            d_label = "IDEAL"
            dist_color = ACCENT_PRIMARY
        elif dist_cm >= 40:
            d_label = "CLOSE"
            dist_color = "#ffaa00"
        else:
            d_label = "TOO CLOSE"
            dist_color = ACCENT_RED

        self.lbl_dist_val.configure(
            text=f"{dist_cm:.0f} cm — {d_label}",
            text_color=dist_color,
        )
        self.dist_bar.set(min(1.0, dist_cm / 120.0))
        self.dist_bar.configure(progress_color=dist_color)

        # Strain ring — RED ≥ 70, ORANGE ≥ 40, else GREEN
        self.strain_ring.set_progress(int(strain))
        if strain >= 70:
            s_text, s_color = "High Strain", ACCENT_RED
        elif strain >= 40:
            s_text, s_color = "Moderate Strain", "#ffaa00"
        else:
            s_text, s_color = "Low Strain", ACCENT_PRIMARY
        self.strain_lbl.configure(text=s_text, text_color=s_color)

    def update_2020_timer(self, elapsed_sec: int):
        """Called by app.py every minute (or second) to advance the 20-20-20 ring."""
        GOAL = 20 * 60  # 20 minutes in seconds
        pct  = min(100, int(elapsed_sec / GOAL * 100))
        self.timer_ring.set_progress(pct)
        m = elapsed_sec // 60
        s = elapsed_sec % 60
        self.timer_lbl.configure(text=f"{m:02d}:{s:02d} of 20 min")

    # ── 40-minute eye-activity countdown ──────────────────────────────────────

    def tick_active(self, is_active: bool):
        """
        Called once per second from app._poll. Advances the 40-min eye-break
        countdown while the user is actively looking at the screen. When the
        timer hits 0 a NotificationPopup is shown and the counter resets.
        """
        if is_active:
            self._40_elapsed += 1

        if self._40_elapsed >= self._40_target:
            self._40_elapsed = 0
            try:
                NotificationPopup(
                    title="Eye Break",
                    message="40 Minutes Active: Please look 20 feet away for 20 seconds.",
                    alert_type="warning",
                )
            except Exception:
                pass

        # Update countdown label (MM:SS remaining)
        remaining = max(0, self._40_target - self._40_elapsed)
        m = remaining // 60
        s = remaining % 60
        color = ACCENT_RED if remaining < 60 else ACCENT_PRIMARY
        self.lbl_40_countdown.configure(
            text=f"{m:02d}:{s:02d}", text_color=color,
        )

    # ── Stare toast helpers ───────────────────────────────────────────────────

    def _show_stare_toast(self):
        try:
            self.lbl_stare_toast.pack(
                in_=self.blink_frame, pady=(0, 14)
            )
        except Exception:
            pass

    def _hide_stare_toast(self):
        try:
            self.lbl_stare_toast.pack_forget()
        except Exception:
            pass
