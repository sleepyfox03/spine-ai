# tabs/dashboard_tab.py
# Dashboard: live Posture Pulse graph, 2D vector spine, Recovery Timer, Recalibrate
import tkinter as tk
import customtkinter as ctk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime
from collections import deque

from config import *
from components.metric_card import MetricCard
from components.ring_chart import RingChart

# ── 2D Vector Spine Renderer ──────────────────────────────────────────────────

SPINE_SEGMENTS = [
    ("Cervical",  "#4fc3f7", 4),   # sky-blue, 4 vertebrae
    ("Thoracic",  "#81c784", 7),   # green,    7 vertebrae (tallest section)
    ("Lumbar",    "#ffb74d", 5),   # amber,    5 vertebrae
]

# Segment indices: 0=Cervical, 1=Thoracic, 2=Lumbar
_SLOUCH_SEGMENT = {
    'fhp':       0,   # Forward Head Posture → Cervical
    'lateral':   1,   # Lateral tilt         → Thoracic
    'slouch':    2,   # Generic slouch       → Lumbar
}


def draw_spine_2d(canvas: tk.Canvas, w: int, h: int,
                  highlight_segment: str = ''):
    """
    Render a 2D anatomical spine with vertebra blocks and labels.
    highlight_segment: 'fhp' | 'lateral' | 'slouch' | '' (none)
    """
    canvas.delete("all")
    cx = w // 2

    # Background gradient line (spine cord)
    canvas.create_line(cx, 10, cx, h - 20, fill="#1a2e1c", width=8)

    seg_hi = _SLOUCH_SEGMENT.get(highlight_segment, -1)

    y = 14
    for seg_idx, (name, color, count) in enumerate(SPINE_SEGMENTS):
        is_bad = seg_idx == seg_hi
        seg_color = ACCENT_RED if is_bad else color
        seg_height = (h - 40) * (count / 16)  # proportional

        vert_h = max(7, int(seg_height / count) - 2)
        gap    = 3

        # Section label on the left
        label_y = y + seg_height // 2
        canvas.create_text(
            cx - 32, label_y,
            text=name[:4], anchor="e",
            fill=seg_color, font=("Segoe UI", 7, "bold")
        )

        # Draw vertebrae blocks
        for v in range(count):
            vy  = y + v * (vert_h + gap)
            vw  = 18 + 4 * (v / max(count - 1, 1))  # lumbar = wider
            col = seg_color

            # Animated shimmer on highlighted segment
            canvas.create_rectangle(
                cx - vw, vy, cx + vw, vy + vert_h,
                fill=col, outline=BG_PRIMARY, width=1
            )
            # Disc between vertebrae
            if v < count - 1:
                disc_y = vy + vert_h + 1
                canvas.create_oval(
                    cx - vw * 0.6, disc_y,
                    cx + vw * 0.6, disc_y + 2,
                    fill="#102114", outline=col, width=1
                )

        y += int(seg_height) + 4

    # Skull base indicator
    canvas.create_oval(cx - 12, 2, cx + 12, 14,
                       fill=BG_CARD, outline=ACCENT_PRIMARY, width=2)
    canvas.create_text(cx, 8, text="↑", fill=ACCENT_PRIMARY, font=("Segoe UI", 7))

    # Alert flash for highlighted
    if highlight_segment:
        alert_msg = {
            'fhp':     "FHP",
            'lateral': "Tilt",
            'slouch':  "Slouch",
        }.get(highlight_segment, "")
        canvas.create_text(
            cx, h - 10, text=f"⚠ {alert_msg}",
            fill=ACCENT_RED, font=("Segoe UI", 8, "bold"), anchor="s"
        )


# ── Dashboard Tab ─────────────────────────────────────────────────────────────

class DashboardTab(ctk.CTkScrollableFrame):

    _MAX_HISTORY = 120   # data points to keep in live graph (~2 min at 1 Hz)
    _RECOVERY_SECONDS = 10

    def __init__(self, parent, app_ref=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._app = app_ref

        # Live graph data
        self._times:  deque = deque(maxlen=self._MAX_HISTORY)
        self._scores: deque = deque(maxlen=self._MAX_HISTORY)

        # Recovery timer state
        self._recovery_active    = False
        self._recovery_countdown = 0
        self._recovery_job       = None
        self._slouch_type        = ''

        self.setup_ui()
        self._draw_empty_graph()

    # ── UI Construction ───────────────────────────────────────────────────────

    def setup_ui(self):
        self.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # ROW 0 — Metric Cards
        self.card_good   = MetricCard(self, title="Good Posture", icon="🟢",
                                      suffix="%", color=ACCENT_PRIMARY)
        self.card_good.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.card_bad    = MetricCard(self, title="Slouch Time", icon="🔴",
                                      suffix="%", color=ACCENT_RED)
        self.card_bad.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")

        self.card_streak = MetricCard(self, title="Best Streak", icon="🔥",
                                      initial_val="00:00", suffix="",
                                      color="#ffaa00")
        self.card_streak.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")

        self.card_score  = MetricCard(self, title="Spine Score", icon="⭐",
                                      suffix="/100", color=ACCENT_PRIMARY)
        self.card_score.grid(row=0, column=3, padx=10, pady=10, sticky="nsew")

        # ROW 1 — Live "Posture Pulse" Timeline
        self._build_live_graph()

        # ROW 2 — 2D Spine Model + Summary
        self._build_spine_row()

        # ROW 3 — Break Compliance + Recovery Timer
        self._build_bottom_row()

        # Seed metric cards with zeros until real data arrives
        self.card_good.set_value(0)
        self.card_bad.set_value(0)
        self.card_streak.val_label.configure(text="00:00")
        self.card_score.set_value(0)

    def _build_live_graph(self):
        self.timeline_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.timeline_frame.grid(
            row=1, column=0, columnspan=4,
            padx=10, pady=15, sticky="nsew"
        )

        hdr = ctk.CTkFrame(self.timeline_frame, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(15, 0))

        ctk.CTkLabel(
            hdr, text="Posture Pulse (Live)",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(side="left")

        # Sensitivity slider — 0.1 (lenient) → 2.0 (strict)
        sens_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        sens_frame.pack(side="right")
        ctk.CTkLabel(
            sens_frame, text="Sensitivity:",
            font=FONT_SMALL, text_color=TEXT_SECONDARY
        ).pack(side="left", padx=(0, 6))
        self.sensitivity_slider = ctk.CTkSlider(
            sens_frame, from_=0.1, to=2.0,
            width=120, height=16,
            fg_color=BG_SECONDARY, progress_color=ACCENT_PRIMARY,
            button_color=ACCENT_PRIMARY,
            command=self._on_sensitivity_change,
        )
        self.sensitivity_slider.set(1.0)
        self.sensitivity_slider.pack(side="left")
        self.sensitivity_lbl = ctk.CTkLabel(
            sens_frame, text="1.0×",
            font=FONT_SMALL, text_color=ACCENT_PRIMARY, width=40
        )
        self.sensitivity_lbl.pack(side="left", padx=4)

        self.fig_timeline, self.ax_timeline = plt.subplots(
            figsize=(10, 2.2), facecolor=BG_CARD
        )
        self.ax_timeline.set_facecolor(BG_CARD)
        self.canvas_timeline = FigureCanvasTkAgg(
            self.fig_timeline, master=self.timeline_frame
        )
        self.canvas_timeline.get_tk_widget().pack(
            fill="both", expand=True, padx=10, pady=10
        )

    def _build_spine_row(self):
        # 2D Spine Model
        self.model_frame = ctk.CTkFrame(
            self, fg_color="#08100a", corner_radius=15,
            border_width=1, border_color=ACCENT_PRIMARY
        )
        self.model_frame.grid(
            row=2, column=0, columnspan=2,
            padx=10, pady=10, sticky="nsew"
        )
        self.model_frame.configure(height=300)
        self.model_frame.grid_propagate(False)

        spine_header = ctk.CTkFrame(self.model_frame, fg_color="transparent")
        spine_header.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(
            spine_header, text="Spinal Health Model",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(side="left")
        self.spine_status_lbl = ctk.CTkLabel(
            spine_header, text="● Good",
            font=FONT_BODY, text_color=ACCENT_PRIMARY
        )
        self.spine_status_lbl.pack(side="right")

        # Canvas for the 2D vector spine
        self.spine_canvas = tk.Canvas(
            self.model_frame, width=200, height=240,
            bg="#08100a", highlightthickness=0
        )
        self.spine_canvas.pack(pady=8)
        draw_spine_2d(self.spine_canvas, 200, 240)

        # Segment legend
        legend = ctk.CTkFrame(self.model_frame, fg_color="transparent")
        legend.pack(pady=(0, 8))
        for name, color, _ in SPINE_SEGMENTS:
            dot = ctk.CTkLabel(legend, text="●", font=FONT_SMALL,
                               text_color=color)
            dot.pack(side="left", padx=(6, 0))
            ctk.CTkLabel(legend, text=name, font=FONT_SMALL,
                         text_color=TEXT_SECONDARY).pack(side="left", padx=(2, 8))

        # AI Insights Frame
        self.summary_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.summary_frame.grid(
            row=2, column=2, columnspan=2,
            padx=10, pady=10, sticky="nsew"
        )
        ctk.CTkLabel(
            self.summary_frame, text="AI Insights",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=20, pady=(20, 10))

        self.insight_lbl = ctk.CTkLabel(
            self.summary_frame,
            text="Waiting for posture data…",
            font=FONT_BODY, text_color=TEXT_SECONDARY,
            justify="left", wraplength=300
        )
        self.insight_lbl.pack(anchor="w", padx=20, pady=(0, 20))

    def _build_bottom_row(self):
        # Break Compliance Ring
        self.ring_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.ring_frame.grid(
            row=3, column=0, columnspan=2,
            padx=10, pady=15, sticky="nsew"
        )
        ctk.CTkLabel(
            self.ring_frame, text="Break Compliance",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(pady=(15, 5))
        self.break_ring = RingChart(
            self.ring_frame, size=160, thickness=15,
            color=ACCENT_PRIMARY, bg_color=BG_CARD
        )
        self.break_ring.pack(pady=10)
        self.break_ring.set_progress(0)

        # ── Recovery Timer Card ───────────────────────────────────────────────
        self.recovery_frame = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY
        )
        self.recovery_frame.grid(
            row=3, column=2, columnspan=2,
            padx=10, pady=15, sticky="nsew"
        )

        ctk.CTkLabel(
            self.recovery_frame, text="Recovery Timer",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        ).pack(pady=(20, 4))

        self.recovery_heading = ctk.CTkLabel(
            self.recovery_frame,
            text="Posture OK ✓",
            font=("Segoe UI", 20, "bold"),
            text_color=ACCENT_PRIMARY
        )
        self.recovery_heading.pack(pady=4)

        self.recovery_countdown_lbl = ctk.CTkLabel(
            self.recovery_frame,
            text="",
            font=("Segoe UI", 40, "bold"),
            text_color=ACCENT_RED
        )
        self.recovery_countdown_lbl.pack(pady=0)

        self.recovery_bar = ctk.CTkProgressBar(
            self.recovery_frame, width=200, height=8,
            fg_color=BG_SECONDARY, progress_color=ACCENT_RED
        )
        self.recovery_bar.set(0)
        self.recovery_bar.pack(pady=(4, 8))

        self.recovery_sub = ctk.CTkLabel(
            self.recovery_frame,
            text="Sit upright to reset the timer",
            font=FONT_SMALL, text_color=TEXT_SECONDARY
        )
        self.recovery_sub.pack(pady=(0, 20))

    # ── Sensitivity slider callback ───────────────────────────────────────────

    def _on_sensitivity_change(self, value: float):
        v = round(value, 1)
        self.sensitivity_lbl.configure(text=f"{v}×")
        if self._app and hasattr(self._app, 'monitor_thread') \
                and self._app.monitor_thread:
            try:
                self._app.monitor_thread.engine.set_sensitivity(v)
            except Exception:
                pass

    # ── Live data push (called from app.py every poll tick) ──────────────────

    def push_posture(self, label: str, score: float,
                     stats: dict | None = None):
        """Update all dashboard widgets with the latest posture result."""
        # Live graph
        self._times.append(datetime.now())
        self._scores.append(score)
        self._redraw_graph()

        # Metric cards
        if stats:
            good_pct = float(stats.get('good_posture_pct', 0))
            active   = max(1, stats.get('active_seconds', 0))
            slouch_pct = round(stats.get('slouch_seconds', 0) / active * 100)
            breaks     = stats.get('breaks_taken', 0)
            best_sec   = stats.get('best_streak_sec', 0)
            spine_score = int(max(0, min(100,
                round(0.7 * good_pct + 0.3 * min(breaks * 20, 100))
            )))
            self.card_good.set_value(int(good_pct))
            self.card_bad.set_value(int(max(0, min(100, slouch_pct))))
            h, m = best_sec // 3600, (best_sec % 3600) // 60
            self.card_streak.val_label.configure(text=f"{h:02d}:{m:02d}")
            self.card_score.set_value(spine_score)
        else:
            self.card_score.set_value(int(score))

        # Break compliance ring
        if stats:
            breaks   = stats.get('breaks_taken', 0)
            expected = max(1, stats.get('sitting_seconds', 0) //
                          (40 * 60))
            pct = min(100, int(breaks / expected * 100)) if expected else 0
            self.break_ring.set_progress(pct)

        # AI Insights
        self._update_insights(label, score, stats)

    def update_slouch_type(self, slouch_type: str):
        """Re-render the 2D spine model for the given slouch_type."""
        self._slouch_type = slouch_type
        draw_spine_2d(self.spine_canvas, 200, 240, highlight_segment=slouch_type)
        if slouch_type:
            label_map = {
                'fhp':     "⚠ Forward Head",
                'lateral': "⚠ Lateral Tilt",
                'slouch':  "⚠ Slouch",
            }
            self.spine_status_lbl.configure(
                text=label_map.get(slouch_type, "⚠ Bad Posture"),
                text_color=ACCENT_RED
            )
        else:
            self.spine_status_lbl.configure(text="● Good", text_color=ACCENT_PRIMARY)

    def update_recovery_timer(self, label: str):
        """
        Called every second by app.py with the current posture label.
        - Starts 10s countdown when label != 'Good'
        - Resets with 'Posture Restored! ✨' when corrected mid-countdown
        """
        is_good = label.lower() == 'good'

        if not is_good:
            if not self._recovery_active:
                # Begin countdown
                self._recovery_active    = True
                self._recovery_countdown = self._RECOVERY_SECONDS
                self._tick_recovery()
        else:
            if self._recovery_active:
                # User corrected posture!
                self._recovery_active    = False
                self._recovery_countdown = 0
                if self._recovery_job:
                    try:
                        self.after_cancel(self._recovery_job)
                    except Exception:
                        pass
                    self._recovery_job = None
                self._show_restored()

    def _tick_recovery(self):
        if not self._recovery_active or self._recovery_countdown <= 0:
            self._recovery_active = False
            return

        self.recovery_heading.configure(
            text="Slouch Detected!",
            text_color=ACCENT_RED
        )
        self.recovery_countdown_lbl.configure(
            text=str(self._recovery_countdown)
        )
        pct = self._recovery_countdown / self._RECOVERY_SECONDS
        self.recovery_bar.set(pct)
        self.recovery_sub.configure(
            text="Sit upright to reset the timer",
            text_color=TEXT_SECONDARY
        )

        self._recovery_countdown -= 1
        self._recovery_job = self.after(1000, self._tick_recovery)

    def _show_restored(self):
        self.recovery_heading.configure(
            text="Posture Restored! ✨",
            text_color=ACCENT_PRIMARY
        )
        self.recovery_countdown_lbl.configure(text="")
        self.recovery_bar.set(0)
        self.recovery_sub.configure(
            text="Great job — keep it up!",
            text_color=ACCENT_PRIMARY
        )
        # Auto-reset label after 4 seconds
        self.after(4000, self._reset_recovery_display)

    def _reset_recovery_display(self):
        if not self._recovery_active:
            self.recovery_heading.configure(
                text="Posture OK ✓",
                text_color=ACCENT_PRIMARY
            )
            self.recovery_sub.configure(
                text="Sit upright to reset the timer",
                text_color=TEXT_SECONDARY
            )

    # ── Live graph renderer ───────────────────────────────────────────────────

    def _draw_empty_graph(self):
        ax = self.ax_timeline
        ax.clear()
        ax.set_facecolor(BG_CARD)
        for sp in ax.spines.values():
            sp.set_color(BG_SECONDARY)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Score", color=TEXT_SECONDARY, fontsize=8)
        ax.text(0.5, 0.5, "Waiting for data…",
                transform=ax.transAxes, color=TEXT_SECONDARY,
                ha='center', va='center', fontsize=10)
        self.fig_timeline.tight_layout(pad=0.4)
        self.canvas_timeline.draw()

    def _redraw_graph(self):
        if len(self._times) < 2:
            return
        ax = self.ax_timeline
        ax.clear()
        ax.set_facecolor(BG_CARD)
        for sp in ['top', 'right']:
            ax.spines[sp].set_visible(False)
        for sp in ['left', 'bottom']:
            ax.spines[sp].set_color(BG_SECONDARY)
        ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)

        times  = list(self._times)
        scores = list(self._scores)

        ax.plot(times, scores, color=ACCENT_PRIMARY, linewidth=2)
        ax.fill_between(times, scores, alpha=0.12, color=ACCENT_PRIMARY)
        ax.set_ylim(0, 100)
        ax.set_ylabel("Score", color=TEXT_SECONDARY, fontsize=8)

        # X-axis: real clock time
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=1))
        ax.tick_params(axis='x', rotation=0, labelsize=7)

        # Green / red threshold line at 65
        ax.axhline(65, color="#2d4d33", linewidth=1, linestyle="--")
        ax.text(times[0], 67, "Threshold", color="#2d4d33", fontsize=7)

        self.fig_timeline.tight_layout(pad=0.4)
        self.canvas_timeline.draw()

    # ── AI Insights text ─────────────────────────────────────────────────────

    def _update_insights(self, label: str, score: float, stats: dict | None):
        lines = []
        if label.lower() == 'good':
            lines.append("🟢 Good posture — keep it up!")
        elif label.lower() == 'forward head':
            lines.append("🔴 Forward Head Posture.\n   Tuck your chin and pull ears back.")
        elif label.lower() == 'lateral tilt':
            lines.append("🟡 Lateral spinal tilt.\n   Level your shoulders and sit evenly.")
        else:
            lines.append("🟡 Slouch detected.\n   Lengthen your spine and open your chest.")

        if stats:
            good_pct = stats.get('good_posture_pct', 0)
            sit_sec  = stats.get('sitting_seconds', 0)
            sit_min  = sit_sec // 60
            if good_pct >= 80:
                lines.append(f"\n💡 Excellent session — {good_pct:.0f}% good posture!")
            elif good_pct >= 50:
                lines.append(f"\n💡 {good_pct:.0f}% good posture. Aim for 80%+.")
            else:
                lines.append(f"\n⚠️ Only {good_pct:.0f}% good posture today.")
            lines.append(f"🪑 Sitting: {sit_min} min")

        self.insight_lbl.configure(text="\n".join(lines))
