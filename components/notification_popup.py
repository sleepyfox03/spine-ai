# components/notification_popup.py
import customtkinter as ctk
from config import *

class NotificationPopup(ctk.CTkToplevel):
    def __init__(self, title="Alert", message="Notification message", alert_type="warning"):
        super().__init__()
        self.overrideredirect(True)
        self.attributes("-topmost", True) # Always on top
        
        color = ACCENT_RED if alert_type == "danger" else ACCENT_PRIMARY
        icon = "⚠️" if alert_type == "danger" else "⏰"
        
        self.configure(fg_color=BG_PRIMARY)
        
        self.frame = ctk.CTkFrame(self, fg_color=BG_CARD, border_width=2, border_color=color, corner_radius=10)
        self.frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Content
        self.lbl_title = ctk.CTkLabel(self.frame, text=f"{icon}  {title}", font=FONT_HEADING, text_color=color)
        self.lbl_title.pack(anchor="w", padx=20, pady=(15, 5))
        
        self.lbl_msg = ctk.CTkLabel(self.frame, text=message, font=FONT_BODY, text_color=TEXT_PRIMARY)
        self.lbl_msg.pack(anchor="w", padx=20, pady=(0, 15))
        
        # Animation positioning
        self.width = 340
        self.height = 100
        self.screen_w = self.winfo_screenwidth()
        self.screen_h = self.winfo_screenheight()
        
        self.current_x = self.screen_w
        self.target_x = self.screen_w - self.width - 20
        self.y_pos = self.screen_h - self.height - 80 # Adjust based on taskbar
        
        self.geometry(f"{self.width}x{self.height}+{self.current_x}+{self.y_pos}")
        
        # Fire animation
        self._slide_in()
        
    def _slide_in(self):
        if self.current_x > self.target_x:
            self.current_x -= 30
            self.geometry(f"{self.width}x{self.height}+{self.current_x}+{self.y_pos}")
            self.after(15, self._slide_in)
        else:
            self.after(4000, self._slide_out) # Stay for 4 seconds, then leave
            
    def _slide_out(self):
        if self.current_x < self.screen_w:
            self.current_x += 30
            self.geometry(f"{self.width}x{self.height}+{self.current_x}+{self.y_pos}")
            self.after(15, self._slide_out)
        else:
            self.destroy()