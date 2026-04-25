# tabs/spine_health_tab.py
import tkinter as tk
import customtkinter as ctk
from config import *


USER_AGE = 25   # mock profile — replace with db_manager.get_profile() age when available


class SpineHealthTab(ctk.CTkScrollableFrame):
    def __init__(self, parent, app_ref=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._app = app_ref

        # Live widget refs populated in setup_ui and updated by refresh()
        self._spine_age_lbl = None
        self._delta_lbl     = None
        self._status_lbl    = None
        self._arc_canvas    = None
        self._bio_age       = USER_AGE

        self.setup_ui()
        self.refresh()

    # ── Live data ─────────────────────────────────────────────────────────────

    def _live_spine_age(self) -> float:
        if self._app is not None and getattr(self._app, 'session_tracker', None):
            return self._app.session_tracker.spine_age(USER_AGE)
        return float(USER_AGE)

    def _live_good_pct(self) -> float:
        if self._app is not None and getattr(self._app, 'session_tracker', None):
            return self._app.session_tracker.get_stats().get('good_posture_pct', 0.0)
        return 0.0

    # ── Refresh (called from app._poll every second) ─────────────────────────

    def refresh(self):
        spine_age = self._live_spine_age()
        bio_age   = self._bio_age
        delta     = round(spine_age - bio_age, 1)
        delta_sign = f"+{delta}" if delta >= 0 else str(delta)
        delta_color = ACCENT_RED if delta > 0 else ACCENT_PRIMARY

        if self._spine_age_lbl:
            self._spine_age_lbl.configure(text=str(spine_age))
        if self._delta_lbl:
            self._delta_lbl.configure(
                text=f"Biological Age: {bio_age}   |   Delta: {delta_sign} years",
                text_color=delta_color,
            )
        if self._status_lbl:
            if spine_age > bio_age:
                self._status_lbl.configure(
                    text="CRITICAL: NEEDS ATTENTION",
                    text_color=ACCENT_RED,
                )
            else:
                self._status_lbl.configure(
                    text="GOOD: HEALTHY SPINE",
                    text_color=ACCENT_PRIMARY,
                )
        if self._arc_canvas is not None:
            self._draw_age_arc(spine_age, bio_age)

    # ── UI construction ───────────────────────────────────────────────────────

    def setup_ui(self):
        self.grid_columnconfigure((0, 1, 2), weight=1)

        # ── SECTION A: Spine Age Hero Card ────────────────────────────────────
        self.hero = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=1, border_color=BG_SECONDARY,
        )
        self.hero.grid(row=0, column=0, columnspan=3,
                       padx=10, pady=(10, 8), sticky="nsew")

        title_row = ctk.CTkFrame(self.hero, fg_color="transparent")
        title_row.pack(anchor="center", pady=(24, 4))

        ctk.CTkLabel(
            title_row,
            text="Your Current Spine Age:  ",
            font=("Segoe UI", 26, "bold"), text_color=TEXT_PRIMARY,
        ).pack(side="left")
        self._spine_age_lbl = ctk.CTkLabel(
            title_row,
            text=str(USER_AGE),
            font=("Segoe UI", 36, "bold"), text_color="#ffaa00",
        )
        self._spine_age_lbl.pack(side="left")

        self._delta_lbl = ctk.CTkLabel(
            self.hero,
            text=f"Biological Age: {USER_AGE}   |   Delta: +0 years",
            font=FONT_HEADING, text_color=ACCENT_PRIMARY,
        )
        self._delta_lbl.pack(pady=(0, 8))

        # Spine-age arc gauge
        self._arc_frame = ctk.CTkFrame(self.hero, fg_color="transparent")
        self._arc_frame.pack(pady=(4, 4))
        self._arc_canvas = tk.Canvas(
            self._arc_frame, width=280, height=50,
            bg=BG_CARD, highlightthickness=0,
        )
        self._arc_canvas.pack()
        self._draw_age_arc(float(USER_AGE), USER_AGE)

        # Status line (Critical / Healthy)
        self._status_lbl = ctk.CTkLabel(
            self.hero,
            text="GOOD: HEALTHY SPINE",
            font=("Segoe UI", 14, "bold"),
            text_color=ACCENT_PRIMARY,
        )
        self._status_lbl.pack(pady=(10, 20))

        # ── SECTION B: Static insights (snapshot) ────────────────────────────
        ctk.CTkLabel(
            self, text="Detailed Posture Insights",
            font=FONT_HEADING, text_color=TEXT_PRIMARY,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(12, 6))

        good_pct = self._live_good_pct()
        bad_pct  = 100.0 - good_pct
        insights = self._build_insights(good_pct, bad_pct)
        for i, (badge, text, color) in enumerate(insights):
            card = ctk.CTkFrame(
                self, fg_color=BG_CARD, corner_radius=10,
                border_width=1, border_color=BG_SECONDARY,
            )
            card.grid(row=2 + i, column=0, columnspan=3,
                      padx=10, pady=4, sticky="nsew")
            ctk.CTkLabel(
                card, text=badge,
                text_color=color, font=FONT_BODY,
                width=110, anchor="w",
            ).pack(side="left", padx=20, pady=14)
            ctk.CTkLabel(
                card, text=text,
                text_color=TEXT_PRIMARY, font=FONT_BODY,
            ).pack(side="left", padx=10)

        # ── SECTION C: Recommended Exercises ─────────────────────────────────
        ctk.CTkLabel(
            self, text="Recommended Exercises",
            font=FONT_HEADING, text_color=TEXT_PRIMARY,
        ).grid(row=6, column=0, columnspan=3,
               sticky="w", padx=20, pady=(24, 8))

        exercises = [
            {"name": "1. Chin Tucks",          "time": "2 mins", "target": "Cervical Spine"},
            {"name": "2. Thoracic Extension",  "time": "3 mins", "target": "Upper Back"},
            {"name": "3. Scapular Retraction", "time": "1 min",  "target": "Shoulders"},
        ]
        for col, ex in enumerate(exercises):
            self._build_exercise_card(col, ex)

    # ── Exercise card ────────────────────────────────────────────────────────

    def _build_exercise_card(self, col: int, ex: dict):
        ex_card = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=15,
            border_width=2, border_color=BG_SECONDARY,
        )
        ex_card.grid(row=7, column=col, padx=10, pady=10, sticky="nsew")

        title = ctk.CTkLabel(
            ex_card, text=ex["name"],
            font=FONT_HEADING, text_color=TEXT_PRIMARY,
        )
        title.pack(pady=(20, 2))
        subtitle = ctk.CTkLabel(
            ex_card,
            text=f"{ex['time']}  ·  {ex['target']}",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        )
        subtitle.pack(pady=(0, 12))

        canvas = ctk.CTkCanvas(
            ex_card, width=120, height=120,
            bg=BG_PRIMARY, bd=0, highlightthickness=0,
        )
        canvas.pack(pady=8)
        self._draw_stick_figure(canvas)

        done_btn = ctk.CTkButton(
            ex_card, text="Mark Done ✓",
            fg_color=BG_SECONDARY, hover_color=ACCENT_PRIMARY,
            text_color=TEXT_PRIMARY,
        )
        done_btn.pack(pady=(8, 20))

        # Minimal-style hover — mirrors MetricCard pattern
        def _enter(_e):
            ex_card.configure(fg_color=BG_CARD_HOVER, border_color=ACCENT_PRIMARY)

        def _leave(_e):
            ex_card.configure(fg_color=BG_CARD, border_color=BG_SECONDARY)

        for w in (ex_card, title, subtitle, canvas):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

    # ── Spine age arc ─────────────────────────────────────────────────────────

    def _draw_age_arc(self, spine_age: float, bio_age: int):
        MAX_AGE = 80
        c = self._arc_canvas
        c.delete("all")

        # Track bar
        c.create_rectangle(20, 20, 260, 32, fill=BG_SECONDARY, outline="")
        # Filled portion to spine age
        filled = max(0, int((spine_age / MAX_AGE) * 240))
        fill_color = ACCENT_RED if spine_age > bio_age else ACCENT_PRIMARY
        if filled > 0:
            c.create_rectangle(20, 20, 20 + filled, 32, fill=fill_color, outline="")
        # Bio age marker
        bio_x = 20 + int((bio_age / MAX_AGE) * 240)
        c.create_rectangle(bio_x - 2, 14, bio_x + 2, 38,
                           fill=ACCENT_PRIMARY, outline="")
        # Labels
        c.create_text(20,  44, text="0",  fill=TEXT_SECONDARY,
                      font=("Segoe UI", 9), anchor="w")
        c.create_text(260, 44, text="80", fill=TEXT_SECONDARY,
                      font=("Segoe UI", 9), anchor="e")
        c.create_text(bio_x, 8, text=f"Bio {bio_age}",
                      fill=ACCENT_PRIMARY,
                      font=("Segoe UI", 8), anchor="center")

    # ── Insights ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_insights(good_pct: float, bad_pct: float) -> list[tuple[str, str, str]]:
        rows = []

        if bad_pct > 50:
            rows.append(("🔴 Critical",
                         f"Bad posture detected {bad_pct:.0f}% of this session.",
                         ACCENT_RED))
        elif bad_pct > 25:
            rows.append(("🟡 Watch",
                         f"Bad posture at {bad_pct:.0f}% — aim to keep it below 20%.",
                         "#ffaa00"))
        else:
            rows.append(("🟢 Good",
                         f"Bad posture only {bad_pct:.0f}% — well done!",
                         ACCENT_PRIMARY))

        if good_pct >= 70:
            rows.append(("🟢 Good",
                         f"Good posture sustained {good_pct:.0f}% of the session.",
                         ACCENT_PRIMARY))
        else:
            rows.append(("🟡 Watch",
                         "Focus on keeping your neck angle below 15° and shoulders level.",
                         "#ffaa00"))

        rows.append(("🟢 Tip",
                     "Take a 30-second break every 40 minutes to reset your spine.",
                     ACCENT_PRIMARY))

        return rows

    # ── Stick figure ─────────────────────────────────────────────────────────

    @staticmethod
    def _draw_stick_figure(c: tk.Canvas):
        c.create_oval(40, 15, 80, 55, outline=ACCENT_PRIMARY, width=2)
        c.create_line(60, 55, 60, 95,  fill=ACCENT_PRIMARY,  width=2)
        c.create_line(25, 68, 95, 68,  fill=TEXT_SECONDARY,  width=2)
        c.create_line(60, 95, 35, 118, fill=ACCENT_PRIMARY,  width=2)
        c.create_line(60, 95, 85, 118, fill=ACCENT_PRIMARY,  width=2)
