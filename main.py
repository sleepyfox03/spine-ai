# main.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Silence OpenCV MSMF warning flood and prefer DirectShow on Windows.
# Must be set BEFORE cv2 is imported (transitively via config / components).
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")

import customtkinter as ctk
from config import *

ctk.set_appearance_mode("dark")


# ── Splash Screen ─────────────────────────────────────────────────────────────

class SplashScreen(ctk.CTkToplevel):
    STEPS = [
        "Loading configuration…",
        "Connecting to database…",
        "Initialising posture engine…",
        "Starting activity monitor…",
        "Building UI…",
        "Spine AI ready.",
    ]

    def __init__(self):
        super().__init__()
        self.overrideredirect(True)

        w, h = 420, 270
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.configure(fg_color=BG_PRIMARY)

        ctk.CTkLabel(self, text="⬡", font=("Segoe UI", 60),
                     text_color=ACCENT_PRIMARY).pack(pady=(36, 4))
        ctk.CTkLabel(self, text=APP_NAME, font=FONT_DISPLAY,
                     text_color=TEXT_PRIMARY).pack()

        self.progress = ctk.CTkProgressBar(
            self, width=300, height=6,
            fg_color=BG_SECONDARY, progress_color=ACCENT_PRIMARY
        )
        self.progress.set(0)
        self.progress.pack(pady=18)

        self.status = ctk.CTkLabel(
            self, text="Starting…",
            font=FONT_SMALL, text_color=TEXT_SECONDARY
        )
        self.status.pack()

    def animate(self, callback):
        import time
        total = len(self.STEPS)
        for i, msg in enumerate(self.STEPS):
            self.progress.set((i + 1) / total)
            self.status.configure(text=msg)
            self.update()
            time.sleep(0.12)
        self.destroy()
        callback()


# ── System Tray ───────────────────────────────────────────────────────────────

def _build_tray_icon(app):
    """Create a pystray system-tray icon. Silently skipped if unavailable."""
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Draw a simple 64×64 green hexagon icon
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        pts = [(32 + 28 * __import__('math').cos(__import__('math').radians(a)),
                32 + 28 * __import__('math').sin(__import__('math').radians(a)))
               for a in range(30, 391, 60)]
        d.polygon(pts, fill=(0, 255, 102))
        d.text((18, 20), "SA", fill=(5, 10, 6))

        def _open(_icon, _item):
            app.root.deiconify()
            app.root.lift()

        def _pause(_icon, _item):
            app.toggle_monitoring()

        def _quit(_icon, _item):
            _icon.stop()
            app.root.quit()

        icon = pystray.Icon(
            "SpineAI", img, "Spine AI",
            menu=pystray.Menu(
                pystray.MenuItem("Open",            _open,  default=True),
                pystray.MenuItem("Pause Monitoring", _pause),
                pystray.MenuItem("Exit",            _quit),
            )
        )
        import threading
        threading.Thread(target=icon.run, daemon=True).start()
    except Exception:
        pass   # pystray not installed — skip silently


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = ctk.CTk()
    root.withdraw()

    splash = SplashScreen()

    def _launch():
        from app import SpineAIApp
        from database.db_manager import DatabaseManager

        app = SpineAIApp(root)

        # First-run check: show calibration wizard if no profile exists
        calib_path = os.path.join(BASE_DIR, "calibration_profile.json")
        if not os.path.exists(calib_path):
            from core.calibration import CalibrationWizard
            CalibrationWizard(root, on_complete=app.start_monitoring)
        else:
            app.start_monitoring()

        _build_tray_icon(app)

    root.after(100, lambda: splash.animate(_launch))
    root.mainloop()
