# core/alert_manager.py
import os
import time
import threading

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BASE_DIR

# Optional audio backends
try:
    import pygame
    pygame.mixer.init()
    _PYGAME = True
except Exception:
    _PYGAME = False

try:
    import pyttsx3
    _TTS = True
except ImportError:
    _TTS = False


class AlertManager:
    """Centralises all alert delivery: voice, sound, and popup callbacks."""

    # Minimum seconds between identical alert types (cooldown)
    _COOLDOWN = {
        'posture':  120,
        'break':    600,
        'blink':    300,
        '20-20-20': 1200,
        'streak':   0,
    }

    def __init__(self, popup_callback=None):
        """
        popup_callback(alert_type, title, message)
            alert_type: 'warning' | 'danger' | 'info' | 'success'
        """
        self.popup_callback = popup_callback
        self._last_alert: dict[str, float] = {}
        self._tts_lock = threading.Lock()
        self._bad_posture_start: float | None = None
        self._BAD_POSTURE_THRESHOLD = 2 * 60  # 2 minutes

        # ── Mute toggle ───────────────────────────────────────────────────────
        self.muted: bool = False

    # ── Mute control ──────────────────────────────────────────────────────────

    def set_muted(self, muted: bool):
        """Silence all TTS and audio alerts.  Popup toasts still appear."""
        self.muted = bool(muted)

    def toggle_mute(self) -> bool:
        """Flip mute state and return new value."""
        self.muted = not self.muted
        return self.muted

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _can_alert(self, key: str) -> bool:
        cooldown = self._COOLDOWN.get(key, 120)
        return time.time() - self._last_alert.get(key, 0) >= cooldown

    def _stamp(self, key: str):
        self._last_alert[key] = time.time()

    def _speak(self, text: str):
        """Speak text via pyttsx3 — silenced when muted."""
        if not _TTS or self.muted:
            return

        def _run():
            with self._tts_lock:
                try:
                    engine = pyttsx3.init()
                    engine.setProperty('rate', 165)
                    voices = engine.getProperty('voices')
                    if len(voices) > 1:
                        engine.setProperty('voice', voices[1].id)
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    def _play(self, filename: str):
        """Play a sound file — silenced when muted."""
        if not _PYGAME or self.muted:
            return
        path = os.path.join(BASE_DIR, "assets", "sounds", filename)
        if not os.path.exists(path):
            return
        try:
            sound = pygame.mixer.Sound(path)
            sound.play()
        except Exception:
            pass

    def _popup(self, alert_type: str, title: str, message: str):
        """Show popup toast — always fires even when muted (visual only)."""
        if self.popup_callback:
            try:
                self.popup_callback(alert_type, title, message)
            except Exception:
                pass

    # ── Public alert triggers ─────────────────────────────────────────────────

    def check_posture(self, label: str):
        """Call every monitoring tick; fires after 2 min of continuous bad posture."""
        if label.lower() != 'good':
            if self._bad_posture_start is None:
                self._bad_posture_start = time.time()
            elif (
                time.time() - self._bad_posture_start >= self._BAD_POSTURE_THRESHOLD
                and self._can_alert('posture')
            ):
                self._stamp('posture')
                self._bad_posture_start = None
                self._fire_posture_alert(label)
        else:
            self._bad_posture_start = None

    def _fire_posture_alert(self, label: str = 'Slouch'):
        label_map = {
            'forward head': 'Forward Head Posture detected. Pull your chin in.',
            'lateral tilt': 'Lateral tilt detected. Level your shoulders.',
            'slouch':       'Posture alert. Please sit upright.',
        }
        msg = label_map.get(label.lower(), 'Posture alert. Please sit upright.')
        self._speak(msg)
        self._play("posture_alert.wav")
        self._popup('danger', "Slouch Detected",
                    f"{label} detected.\nStraighten your back now.")

    def trigger_break_alert(self):
        if not self._can_alert('break'):
            return
        self._stamp('break')
        self._speak("You've been sitting for 40 minutes. Time for a break.")
        self._play("break_alert.wav")
        self._popup('warning', "Time for a Break",
                    "You've been sitting for 40 minutes.\nStand up and stretch!")

    def trigger_blink_alert(self):
        """Low blink rate detected (BPM < 10) — 'Remember to Blink' toast."""
        if not self._can_alert('blink'):
            return
        self._stamp('blink')
        self._speak("Remember to blink. Your blink rate is low.")
        self._popup('warning', "Remember to Blink 👁",
                    "Blink rate below 10 BPM detected.\n"
                    "Look away and blink slowly a few times.")

    def trigger_stare_warning(self):
        """Alias used by eye_health_tab to fire the blink reminder toast."""
        self.trigger_blink_alert()

    def trigger_20_20_20(self):
        if not self._can_alert('20-20-20'):
            return
        self._stamp('20-20-20')
        self._speak("Look 20 feet away for 20 seconds.")
        self._popup('info', "20-20-20 Rule",
                    "Look 20 feet away for 20 seconds\nto reduce eye strain.")

    def trigger_good_streak(self, minutes: int):
        self._speak(f"Excellent! {minutes} minutes of perfect posture.")
        self._popup('success', "Great Posture! 🔥",
                    f"{minutes} minutes of perfect posture streak!\nKeep it up!")
