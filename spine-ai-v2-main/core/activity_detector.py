# core/activity_detector.py
import time
import threading

try:
    from pynput import keyboard, mouse
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False


class ActivityDetector:
    IDLE_THRESHOLD = 5 * 60  # 5 minutes of no input = inactive

    def __init__(self):
        self._last_event = time.time()
        self._lock = threading.Lock()
        self._kb_listener = None
        self._mouse_listener = None

    def start(self):
        if not _PYNPUT_AVAILABLE:
            return
        try:
            self._kb_listener = keyboard.Listener(
                on_press=self._on_event,
                suppress=False
            )
            self._mouse_listener = mouse.Listener(
                on_move=self._on_event,
                on_click=self._on_event,
                on_scroll=self._on_event
            )
            self._kb_listener.start()
            self._mouse_listener.start()
        except Exception:
            pass

    def stop(self):
        try:
            if self._kb_listener:
                self._kb_listener.stop()
            if self._mouse_listener:
                self._mouse_listener.stop()
        except Exception:
            pass

    def _on_event(self, *args):
        with self._lock:
            self._last_event = time.time()

    def is_active(self) -> bool:
        with self._lock:
            return (time.time() - self._last_event) < self.IDLE_THRESHOLD

    def idle_seconds(self) -> float:
        with self._lock:
            return time.time() - self._last_event
