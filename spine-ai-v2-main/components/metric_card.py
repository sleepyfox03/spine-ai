# components/metric_card.py
import customtkinter as ctk
from config import *

class MetricCard(ctk.CTkFrame):
    def __init__(self, parent, title, initial_val="0", icon="📊", suffix="", color=ACCENT_PRIMARY):
        # We use a solid border that is initially dark
        super().__init__(parent, fg_color=BG_CARD, corner_radius=15, border_width=2, border_color=BG_SECONDARY)
        
        self.target_val = 0
        self.current_val = 0
        self.suffix = suffix
        self.color = color
        
        # Top layout (Icon + Title)
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.pack(fill="x", padx=15, pady=(15, 5))
        
        self.icon_label = ctk.CTkLabel(self.top_frame, text=icon, font=("Segoe UI", 20), text_color=color)
        self.icon_label.pack(side="left")
        
        self.title_label = ctk.CTkLabel(self.top_frame, text=title, font=FONT_BODY, text_color=TEXT_SECONDARY)
        self.title_label.pack(side="left", padx=10)
        
        # Bottom layout (Value)
        self.val_label = ctk.CTkLabel(self, text=f"{initial_val}{self.suffix}", font=FONT_DISPLAY, text_color=TEXT_PRIMARY)
        self.val_label.pack(anchor="w", padx=20, pady=(0, 15))
        
        # Hover bindings (Apply to frame and all children so hover doesn't break)
        self.bind("<Enter>", self.on_hover)
        self.bind("<Leave>", self.on_leave)
        for widget in [self.top_frame, self.icon_label, self.title_label, self.val_label]:
            widget.bind("<Enter>", self.on_hover)
            widget.bind("<Leave>", self.on_leave)
            
    def on_hover(self, event):
        self.configure(fg_color=BG_CARD_HOVER, border_color=self.color)
        
    def on_leave(self, event):
        self.configure(fg_color=BG_CARD, border_color=BG_SECONDARY)
        
    def set_value(self, target):
        """Triggers the count-up animation"""
        self.target_val = int(target)
        self.current_val = 0
        self._update_value()
        
    def _update_value(self):
        if self.current_val < self.target_val:
            # Dynamic step size so big numbers animate just as fast as small ones
            step = max(1, self.target_val // 20)
            self.current_val = min(self.target_val, self.current_val + step)
            self.val_label.configure(text=f"{self.current_val}{self.suffix}")
            self.after(30, self._update_value)