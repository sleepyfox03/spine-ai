# components/sidebar.py
import customtkinter as ctk
from config import *


class ProfileSidebar(ctk.CTkFrame):
    """
    Slide-out profile panel with Mute Alerts toggle.
    The mute switch is connected to app.alert_manager via set_muted().
    """

    def __init__(self, parent, app_controller, **kwargs):
        super().__init__(
            parent, width=300,
            fg_color=BG_CARD, corner_radius=0,
            border_width=1, border_color=BG_SECONDARY,
            **kwargs
        )
        self.app = app_controller
        self._mute_var = ctk.BooleanVar(value=False)
        self.setup_ui()
        self.refresh_profile()

    def setup_ui(self):
        # ── Header: Avatar & Name ─────────────────────────────────────────────
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", pady=(30, 10), padx=20)

        self.avatar = ctk.CTkLabel(
            self.header_frame, text="👤",
            font=("Segoe UI", 50), text_color=TEXT_PRIMARY
        )
        self.avatar.pack()

        self.name_label = ctk.CTkLabel(
            self.header_frame, text="SpineAI User",
            font=FONT_HEADING, text_color=TEXT_PRIMARY
        )
        self.name_label.pack(pady=(10, 0))

        self.score_label = ctk.CTkLabel(
            self.header_frame, text="Spine Score: —/100",
            font=FONT_BODY, text_color=ACCENT_PRIMARY
        )
        self.score_label.pack()

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=BG_SECONDARY).pack(
            fill="x", padx=20, pady=20
        )

        # ── Menu Items ────────────────────────────────────────────────────────
        menu_items = [
            ("👤  Profile",         self._open_profile),
            ("📊  My Stats",        self._placeholder),
            ("🎯  Goals",           self._placeholder),
            ("📅  History",         self._placeholder),
            ("🔔  Notifications",   self._placeholder),
        ]
        for text, cmd in menu_items:
            ctk.CTkButton(
                self, text=text, anchor="w",
                fg_color="transparent", text_color=TEXT_SECONDARY,
                hover_color=BG_CARD_HOVER,
                font=FONT_BODY, command=cmd, height=40
            ).pack(fill="x", padx=10, pady=2)

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=BG_SECONDARY).pack(
            fill="x", padx=20, pady=20
        )

        # ── Mute Alerts Switch ────────────────────────────────────────────────
        mute_row = ctk.CTkFrame(self, fg_color="transparent")
        mute_row.pack(fill="x", padx=20, pady=(0, 6))

        ctk.CTkLabel(
            mute_row, text="🔕  Mute Alerts",
            font=FONT_BODY, text_color=TEXT_SECONDARY, anchor="w"
        ).pack(side="left", fill="x", expand=True)

        self.mute_switch = ctk.CTkSwitch(
            mute_row,
            text="",
            variable=self._mute_var,
            onvalue=True,
            offvalue=False,
            fg_color=BG_SECONDARY,
            progress_color=ACCENT_RED,
            button_color=TEXT_PRIMARY,
            button_hover_color=ACCENT_PRIMARY,
            command=self._on_mute_toggle,
            width=46, height=22,
        )
        self.mute_switch.pack(side="right")

        self.mute_status_lbl = ctk.CTkLabel(
            self, text="Voice & sound alerts are ON",
            font=FONT_SMALL, text_color=TEXT_SECONDARY
        )
        self.mute_status_lbl.pack(padx=20, anchor="w")

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=BG_SECONDARY).pack(
            fill="x", padx=20, pady=16
        )

        # ── Bottom Actions ────────────────────────────────────────────────────
        self.export_btn = ctk.CTkButton(
            self, text="Export Report",
            fg_color=BG_SECONDARY, text_color=TEXT_PRIMARY,
            hover_color=BG_CARD_HOVER, height=40,
            command=self._placeholder
        )
        self.export_btn.pack(fill="x", padx=20, pady=5)

        self.logout_btn = ctk.CTkButton(
            self, text="Logout",
            fg_color="transparent", text_color=ACCENT_RED,
            hover_color=BG_CARD_HOVER, height=40,
            command=self._placeholder
        )
        self.logout_btn.pack(fill="x", padx=20, pady=5)

    # ── Mute toggle ───────────────────────────────────────────────────────────

    def _on_mute_toggle(self):
        muted = self._mute_var.get()
        # Propagate to AlertManager
        if hasattr(self.app, 'alert_manager') and self.app.alert_manager:
            self.app.alert_manager.set_muted(muted)

        if muted:
            self.mute_status_lbl.configure(
                text="Alerts muted (popups still visible)",
                text_color=ACCENT_RED
            )
        else:
            self.mute_status_lbl.configure(
                text="Voice & sound alerts are ON",
                text_color=TEXT_SECONDARY
            )

    def update_score(self, score: int):
        """Called from app.py to keep the spine score current."""
        self.score_label.configure(text=f"Spine Score: {score}/100")

    # ── Profile ──────────────────────────────────────────────────────────────

    def refresh_profile(self):
        """Read the saved name from db_manager and update the avatar label."""
        try:
            from database.db_manager import db
            p = db.get_profile() or {}
            name = (p.get('name') or 'SpineAI User').strip() or 'SpineAI User'
            self.name_label.configure(text=name)
        except Exception:
            pass

    def _open_profile(self):
        from components.profile_dialog import ProfileDialog
        try:
            ProfileDialog(self.app.root, on_saved=self.refresh_profile)
        except Exception:
            pass

    # ── Placeholder ───────────────────────────────────────────────────────────

    def _placeholder(self):
        pass
