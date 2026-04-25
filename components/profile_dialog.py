# components/profile_dialog.py
import customtkinter as ctk
from config import *


class ProfileDialog(ctk.CTkToplevel):
    """
    Modal profile editor — name, age, daily sitting goal, daily break goal.
    Persists via db_manager.save_profile().
    """

    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.title("User Profile")
        self.configure(fg_color=BG_PRIMARY)
        self.resizable(False, False)
        self._on_saved = on_saved

        # Center on the parent window
        w, h = 440, 600
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        except Exception:
            x = y = 100
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.minsize(w, h)
        self.update_idletasks()
        try:
            self.transient(parent)
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:
            pass

        # Load current profile (fall back to defaults)
        try:
            from database.db_manager import db
            p = db.get_profile() or {}
        except Exception:
            p = {}
        self._initial = {
            'name':         p.get('name', 'User'),
            'age':          p.get('age', 25),
            'goal_hrs':     p.get('goal_sitting_limit_hrs', 6.0),
            'goal_breaks':  p.get('goal_breaks_per_day', 8),
        }

        self._build()

    def _build(self):
        ctk.CTkLabel(
            self, text="User Profile",
            font=("Segoe UI", 22, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(pady=(24, 4))

        ctk.CTkLabel(
            self,
            text="Edit your details — these tune the live metrics.",
            font=FONT_SMALL, text_color=TEXT_SECONDARY,
        ).pack(pady=(0, 18))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(padx=30, fill="x")

        self._entry_name        = self._field(form, "Name",                          str(self._initial['name']))
        self._entry_age         = self._field(form, "Age",                           str(self._initial['age']))
        self._entry_goal_hrs    = self._field(form, "Daily sitting goal (hours)",    str(self._initial['goal_hrs']))
        self._entry_goal_breaks = self._field(form, "Daily break goal (count)",      str(self._initial['goal_breaks']))

        self._status = ctk.CTkLabel(
            self, text="", font=FONT_SMALL, text_color=ACCENT_RED,
        )
        self._status.pack(pady=(8, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(20, 24))

        ctk.CTkButton(
            btn_row, text="Cancel",
            fg_color=BG_SECONDARY, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRIMARY, width=120,
            command=self.destroy,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_row, text="Save & Update",
            fg_color=ACCENT_PRIMARY, hover_color="#00cc52",
            text_color=BG_PRIMARY, width=160, height=40,
            font=FONT_BODY,
            command=self._save,
        ).pack(side="left", padx=8)

    def _field(self, parent, label: str, initial: str) -> ctk.CTkEntry:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=6)
        ctk.CTkLabel(
            row, text=label, font=FONT_BODY,
            text_color=TEXT_SECONDARY, anchor="w",
        ).pack(anchor="w")
        entry = ctk.CTkEntry(
            row, font=FONT_BODY,
            fg_color=BG_CARD, border_color=BG_SECONDARY,
            text_color=TEXT_PRIMARY, height=32,
        )
        entry.insert(0, initial)
        entry.pack(fill="x", pady=(2, 0))
        return entry

    def _save(self):
        try:
            name = self._entry_name.get().strip() or "User"
            age = int(self._entry_age.get().strip())
            if not (1 <= age <= 120):
                raise ValueError("age must be between 1 and 120")
            goal_hrs = float(self._entry_goal_hrs.get().strip())
            if not (0 < goal_hrs <= 24):
                raise ValueError("sitting goal must be between 0 and 24 hours")
            goal_breaks = int(self._entry_goal_breaks.get().strip())
            if not (0 <= goal_breaks <= 50):
                raise ValueError("break goal must be between 0 and 50")
        except ValueError as e:
            self._status.configure(text=f"Invalid input: {e}")
            return

        try:
            from database.db_manager import db
            db.save_profile(
                name=name, age=age,
                goal_hrs=goal_hrs, goal_breaks=goal_breaks,
            )
        except Exception as e:
            self._status.configure(text=f"DB error: {e}")
            return

        if self._on_saved:
            try:
                self._on_saved()
            except Exception:
                pass
        self.destroy()
