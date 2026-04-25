# components/live_view.py
import os
import sys
import math
import tkinter as tk
import customtkinter as ctk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import *

try:
    import cv2
    from PIL import Image, ImageTk
    _CV2 = True
except ImportError:
    _CV2 = False


class LiveViewWindow(ctk.CTkToplevel):
    """
    Floating window that shows the live webcam feed (with MediaPipe skeleton)
    and a real-time posture-score gauge.

    Reads from the MonitoringThread's shared attributes:
        latest_annotated, latest_score, latest_label,
        latest_neck, latest_sh_tilt, latest_blink
    """

    UPDATE_MS = 100   # 10 fps for the display

    def __init__(self, parent, monitor_thread):
        super().__init__(parent)
        self.monitor_thread = monitor_thread
        self._running = True
        self._photo   = None

        self.title("Spine AI — Live Monitor")
        self.attributes("-topmost", True)
        self.configure(fg_color=BG_PRIMARY)
        self.resizable(False, False)

        w, h = 720, 600
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self._build_ui()
        self._update_loop()
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        header = ctk.CTkFrame(
            self, fg_color=BG_SECONDARY, height=52, corner_radius=0
        )
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="⬡  Live Posture Monitor",
            font=FONT_HEADING, text_color=ACCENT_PRIMARY,
        ).pack(side="left", padx=16)

        ctk.CTkButton(
            header, text="✕  Close Monitoring",
            font=FONT_BODY, width=150, height=32,
            fg_color=ACCENT_RED, text_color="#ffffff",
            hover_color="#cc2222", corner_radius=8,
            command=self._close,
        ).pack(side="right", padx=12, pady=10)

        # Content row
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=10, pady=10)
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=1)
        row.grid_rowconfigure(0, weight=1)

        # Camera feed
        self.cam_label = ctk.CTkLabel(
            row,
            text="Waiting for camera feed…",
            font=FONT_BODY, text_color=TEXT_SECONDARY,
            width=500, height=400,
            fg_color=BG_CARD, corner_radius=12,
        )
        self.cam_label.grid(row=0, column=0, padx=(0, 8), sticky="nsew")

        # Score panel
        panel = ctk.CTkFrame(row, fg_color=BG_CARD, corner_radius=12)
        panel.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(
            panel, text="POSTURE\nSCORE",
            font=FONT_BODY, text_color=TEXT_SECONDARY, justify="center",
        ).pack(pady=(20, 4))

        # Arc gauge canvas
        self.gauge_canvas = tk.Canvas(
            panel, width=150, height=150,
            bg=BG_CARD, highlightthickness=0,
        )
        self.gauge_canvas.pack(pady=4)

        self.score_lbl = ctk.CTkLabel(
            panel, text="—",
            font=FONT_DISPLAY, text_color=ACCENT_PRIMARY,
        )
        self.score_lbl.pack(pady=2)

        self.label_lbl = ctk.CTkLabel(
            panel, text="Initialising…",
            font=FONT_BODY, text_color=TEXT_SECONDARY,
        )
        self.label_lbl.pack(pady=2)

        # Divider
        ctk.CTkFrame(panel, fg_color=BG_SECONDARY, height=1).pack(
            fill="x", padx=16, pady=12
        )

        # Detail stats
        self.neck_lbl  = ctk.CTkLabel(panel, text="Neck Angle:  —°",
                                       font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.neck_lbl.pack(pady=3)

        self.sh_lbl    = ctk.CTkLabel(panel, text="Shoulder Tilt:  —",
                                       font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.sh_lbl.pack(pady=3)

        self.blink_lbl = ctk.CTkLabel(panel, text="Blink Rate:  — /min",
                                       font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.blink_lbl.pack(pady=3)

        self.tri_lbl   = ctk.CTkLabel(panel, text="Triangle Area:  —",
                                       font=FONT_SMALL, text_color=TEXT_SECONDARY)
        self.tri_lbl.pack(pady=3)

    # ── Gauge drawing ─────────────────────────────────────────────────────────

    def _draw_gauge(self, score: float, label: str):
        c = self.gauge_canvas
        c.delete("all")

        color = (
            ACCENT_PRIMARY if label == 'Good'
            else ACCENT_RED if label == 'Slouch'
            else "#f59e0b"   # amber for Forward Head
        )

        # Background ring
        c.create_arc(12, 12, 138, 138, start=0, extent=360,
                     fill=BG_SECONDARY, outline=BG_SECONDARY)

        # Score arc — 270° sweep starting at bottom-left (225°)
        extent = -(score / 100) * 270
        c.create_arc(18, 18, 132, 132, start=225, extent=extent,
                     style="arc", outline=color, width=14)

        # Score text in centre
        c.create_text(
            75, 75, text=f"{score:.0f}",
            fill=color, font=("Segoe UI", 24, "bold"),
        )

    # ── Update loop ───────────────────────────────────────────────────────────

    def _update_loop(self):
        if not self._running:
            return

        mt = self.monitor_thread

        # Camera feed
        if _CV2 and mt and mt.latest_annotated is not None:
            try:
                frame   = mt.latest_annotated
                resized = cv2.resize(frame, (500, 400))
                img     = Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
                self._photo = ctk.CTkImage(light_image=img, dark_image=img, size=(500, 400))
                self.cam_label.configure(image=self._photo, text="")
            except Exception:
                pass

        # Score + stats
        if mt:
            score = getattr(mt, 'latest_score',   0.0)
            label = getattr(mt, 'latest_label',   '—')
            neck  = getattr(mt, 'latest_neck',    0.0)
            sh    = getattr(mt, 'latest_sh_tilt', 0.0)
            blink = getattr(mt, 'latest_blink',   0.0)

            self._draw_gauge(score, label)
            self.score_lbl.configure(text=f"{score:.0f}")

            color = (
                ACCENT_PRIMARY if label == 'Good'
                else ACCENT_RED if label == 'Slouch'
                else "#f59e0b"
            )
            self.label_lbl.configure(text=label, text_color=color)
            self.neck_lbl.configure( text=f"Neck Angle:   {neck:.1f}°")
            self.sh_lbl.configure(   text=f"Shoulder Tilt:  {sh:.1f}")
            self.blink_lbl.configure(text=f"Blink Rate:   {blink:.0f} /min")

            tri = getattr(mt, 'latest_triangle', 0.0)
            self.tri_lbl.configure(text=f"Triangle Area:  {tri:.1f}")

        self.after(self.UPDATE_MS, self._update_loop)

    # ── Close ─────────────────────────────────────────────────────────────────

    def _close(self):
        self._running = False
        self.destroy()
