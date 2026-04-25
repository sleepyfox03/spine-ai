# config.py
import os

# App Info
APP_NAME = "SPINE AI"
VERSION = "1.0.0"

# UI Colors (Dark Green Theme)
BG_PRIMARY      = "#050a06"  # Deepest green-black (main background)
BG_SECONDARY    = "#0a140c"  # Slightly lighter (top bar)
BG_CARD         = "#102114"  # Sidebar / Inactive elements
BG_CARD_HOVER   = "#172e1c"  # Hover states
ACCENT_PRIMARY  = "#00ff66"  # Vibrant neon green (Active tabs, logos)
ACCENT_RED      = "#ff4444"  # Close button
TEXT_PRIMARY    = "#e6f5ea"  # Off-white with a green tint
TEXT_SECONDARY  = "#8ab397"  # Muted green-gray for secondary text

# Typography
FONT_DISPLAY    = ("Segoe UI", 28, "bold")
FONT_HEADING    = ("Segoe UI", 16, "bold")
FONT_BODY       = ("Segoe UI", 12, "bold")
FONT_SMALL      = ("Segoe UI", 10)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "spine_ai.db")