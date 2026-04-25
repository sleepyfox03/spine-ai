# components/ring_chart.py
import tkinter as tk
from config import *

class RingChart(tk.Canvas):
    def __init__(self, parent, size=150, thickness=12, color=ACCENT_PRIMARY, bg_color=BG_PRIMARY):
        # bd=0 and highlightthickness=0 ensure NO white borders
        super().__init__(parent, width=size, height=size, bg=bg_color, bd=0, highlightthickness=0)
        
        self.size = size
        self.thickness = thickness
        self.color = color
        self.target_pct = 0
        self.current_pct = 0
        
        self.center = size / 2
        # Bounding box for the arc
        self.box = (self.thickness/2, self.thickness/2, size - self.thickness/2, size - self.thickness/2)
        
        # 1. Draw Background Track
        self.create_oval(self.box, outline=BG_SECONDARY, width=self.thickness)
        
        # 2. Draw Progress Arc (Starts at top: 90 degrees)
        self.arc = self.create_arc(self.box, start=90, extent=0, outline=self.color, width=self.thickness, style=tk.ARC)
        
        # 3. Draw Center Text
        self.text_item = self.create_text(self.center, self.center, text="0%", fill=TEXT_PRIMARY, font=FONT_HEADING)
        
    def set_progress(self, percentage):
        """Animates the ring drawing itself"""
        self.target_pct = int(percentage)
        self.current_pct = 0
        self._animate_ring()
        
    def _animate_ring(self):
        if self.current_pct < self.target_pct:
            self.current_pct += max(1, self.target_pct // 30)
            if self.current_pct > self.target_pct:
                self.current_pct = self.target_pct
                
            # Tkinter draws counter-clockwise, so we use negative extent
            extent = -(self.current_pct / 100.0) * 359.99 
            
            self.itemconfig(self.arc, extent=extent)
            self.itemconfig(self.text_item, text=f"{self.current_pct}%")
            
            self.after(20, self._animate_ring)