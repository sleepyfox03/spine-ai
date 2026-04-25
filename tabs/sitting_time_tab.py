# tabs/sitting_time_tab.py
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from config import *
from components.metric_card import MetricCard
from components.ring_chart import RingChart

class SittingTimeTab(ctk.CTkScrollableFrame):
    def __init__(self, parent, app_ref=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._app = app_ref
        self._last_timeline_len = -1   # cache to skip redundant matplotlib redraws
        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        # 4-column grid layout for the stat cards
        self.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # ==========================================
        # SECTION A: Today's Activity Timeline
        # ==========================================
        self.timeline_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=15, border_width=1, border_color=BG_SECONDARY)
        self.timeline_frame.grid(row=0, column=0, columnspan=4, padx=10, pady=(10, 20), sticky="nsew")

        ctk.CTkLabel(self.timeline_frame, text="Activity Timeline (6 AM - 12 AM)", font=FONT_HEADING, text_color=TEXT_PRIMARY).pack(anchor="w", padx=20, pady=(20, 5))
        
        # Legend
        legend_frame = ctk.CTkFrame(self.timeline_frame, fg_color="transparent")
        legend_frame.pack(anchor="w", padx=20, pady=5)
        legends = [("🟢 Good Posture", ACCENT_PRIMARY), ("🟡 Bad Posture", "#ffaa00"), ("🔴 Sedentary", ACCENT_RED), ("⚪ Away", TEXT_SECONDARY)]
        for text, color in legends:
            ctk.CTkLabel(legend_frame, text=text, text_color=color, font=FONT_SMALL).pack(side="left", padx=(0, 15))

        # Embed Matplotlib Bar (Horizontal)
        self.fig_bar, self.ax_bar = plt.subplots(figsize=(10, 1.5), facecolor=BG_CARD)
        self.ax_bar.set_facecolor(BG_CARD)
        self.canvas_bar = FigureCanvasTkAgg(self.fig_bar, master=self.timeline_frame)
        self.canvas_bar.get_tk_widget().pack(fill="x", padx=10, pady=10)

        # ==========================================
        # SECTION B: Stats Row
        # ==========================================
        self.card_sitting = MetricCard(self, title="Sitting Time", icon="🪑",
                                       initial_val="00:00", suffix="",
                                       color=ACCENT_RED)
        self.card_sitting.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        self.card_active = MetricCard(self, title="Active Time", icon="⌨️",
                                      initial_val="00:00", suffix="",
                                      color=ACCENT_PRIMARY)
        self.card_active.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

        self.card_break = MetricCard(self, title="Break Time", icon="🚶",
                                     initial_val="00:00", suffix="",
                                     color="#ffaa00")
        self.card_break.grid(row=1, column=2, padx=10, pady=10, sticky="nsew")

        self.card_quality = MetricCard(self, title="Posture Quality", icon="✨", suffix="%", color=ACCENT_PRIMARY)
        self.card_quality.grid(row=1, column=3, padx=10, pady=10, sticky="nsew")

        # ==========================================
        # SECTION C & D: Break Compliance & Insights
        # ==========================================
        self.ring_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=15, border_width=1, border_color=BG_SECONDARY)
        self.ring_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=15, sticky="nsew")
        ctk.CTkLabel(self.ring_frame, text="Break Compliance", font=FONT_HEADING, text_color=TEXT_PRIMARY).pack(pady=(15, 5))
        self.break_ring = RingChart(self.ring_frame, size=150, thickness=12, color=ACCENT_PRIMARY, bg_color=BG_CARD)
        self.break_ring.pack(pady=10)
        ctk.CTkLabel(self.ring_frame, text="You took 3 of 7 recommended breaks today.", font=FONT_BODY, text_color=TEXT_SECONDARY).pack(pady=(5, 20))

        self.insight_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=15, border_width=1, border_color=BG_SECONDARY)
        self.insight_frame.grid(row=2, column=2, columnspan=2, padx=10, pady=15, sticky="nsew")
        ctk.CTkLabel(self.insight_frame, text="What Your Pattern Says", font=FONT_HEADING, text_color=TEXT_PRIMARY).pack(anchor="w", padx=20, pady=(20, 10))
        
        pattern_text = (
            "Today you sat for 5.5 hours with only 3 breaks. This puts your activity level in the Sedentary category. "
            "Studies link this pattern with an 18% higher risk of lower back disc degeneration. "
            "\n\n💡 Longest unbroken sitting session: 1h 47m."
        )
        ctk.CTkLabel(self.insight_frame, text=pattern_text, font=FONT_BODY, text_color=TEXT_SECONDARY, justify="left", wraplength=400).pack(anchor="w", padx=20)

        # ==========================================
        # SECTION E: Medical Education Gallery
        # ==========================================
        ctk.CTkLabel(self, text="Sedentary Lifestyle Effects", font=FONT_HEADING, text_color=TEXT_PRIMARY).grid(row=3, column=0, columnspan=4, sticky="w", padx=20, pady=(20, 10))

        gallery_items = [
            ("Lumbar Compression", "Prolonged sitting compresses L4-L5 discs."),
            ("Sciatic Nerve", "Chair pressure irritates the sciatic nerve pathway."),
            ("Blood Flow", "Lower limb circulation drops by 50% after 1 hour.")
        ]

        # Use columns 0, 1, 2 for the 3 gallery items (span the last one to fill)
        for i, (title, desc) in enumerate(gallery_items):
            col_span = 1 if i < 2 else 2
            card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10, border_width=1, border_color=BG_SECONDARY)
            card.grid(row=4, column=i, columnspan=col_span, padx=10, pady=10, sticky="nsew")
            
            # Placeholder for medical image
            img_placeholder = ctk.CTkFrame(card, height=100, fg_color=BG_SECONDARY, corner_radius=8)
            img_placeholder.pack(fill="x", padx=10, pady=10)
            ctk.CTkLabel(img_placeholder, text="[ Medical Diagram ]", text_color=ctk.CTkLabel(img_placeholder, text="[ Medical Diagram ]", text_color=TEXT_SECONDARY).place(relx=0.5, rely=0.5, anchor="center")).place(relx=0.5, rely=0.5, anchor="center")
            
            ctk.CTkLabel(card, text=title, font=FONT_BODY, text_color=ACCENT_RED).pack(anchor="w", padx=15, pady=(5, 0))
            ctk.CTkLabel(card, text=desc, font=FONT_SMALL, text_color=TEXT_SECONDARY, wraplength=200, justify="left").pack(anchor="w", padx=15, pady=(0, 15))

    @staticmethod
    def _format_hhmm(seconds: int) -> str:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h:02d}:{m:02d}"

    def refresh(self):
        """Pull live session stats and update the 4 cards + break ring."""
        stats = None
        if self._app is not None and getattr(self._app, 'session_tracker', None):
            stats = self._app.session_tracker.get_stats()

        if stats:
            self.card_sitting.val_label.configure(
                text=self._format_hhmm(stats.get('total_seconds', 0)))
            self.card_active.val_label.configure(
                text=self._format_hhmm(stats.get('active_seconds', 0)))
            self.card_break.val_label.configure(
                text=self._format_hhmm(stats.get('break_seconds', 0)))
            self.card_quality.set_value(int(stats.get('good_posture_pct', 0)))

            # Break compliance: actual breaks vs expected (1 per 40 min sitting)
            sitting  = stats.get('sitting_seconds', 0)
            expected = max(1, sitting // (40 * 60))
            breaks   = stats.get('breaks_taken', 0)
            pct      = min(100, int(breaks / expected * 100)) if expected else 0
            self.break_ring.set_progress(pct)
        else:
            self.card_quality.set_value(0)
            self.break_ring.set_progress(0)

        # Activity timeline — per-minute state from SessionTracker
        if self._app and getattr(self._app, 'session_tracker', None):
            minutes = self._app.session_tracker.get_minute_timeline()
        else:
            minutes = []
        self._render_timeline(minutes)

    def _render_timeline(self, minutes: list[str]):
        # Skip redraw if no new minute has rolled over (matplotlib redraws are
        # expensive — only do it on minute boundaries).
        if len(minutes) == self._last_timeline_len:
            return
        self._last_timeline_len = len(minutes)

        COLOR_MAP = {
            'good': ACCENT_PRIMARY,
            'bad':  "#ffaa00",
            'away': TEXT_SECONDARY,
        }

        self.ax_bar.clear()
        self.ax_bar.axis('off')

        i = 0
        while i < len(minutes):
            j = i
            while j < len(minutes) and minutes[j] == minutes[i]:
                j += 1
            width = j - i
            color = COLOR_MAP.get(minutes[i], TEXT_SECONDARY)
            self.ax_bar.barh(0, width, left=i, height=0.5, color=color)
            i = j

        self.ax_bar.set_xlim(0, max(60, len(minutes)))
        self.ax_bar.set_ylim(-0.5, 0.5)
        self.canvas_bar.draw()