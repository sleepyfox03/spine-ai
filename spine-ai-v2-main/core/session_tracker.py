# core/session_tracker.py
import threading
import time
from datetime import datetime


class SessionTracker:
    """
    Tracks sitting/break time, posture quality, slouch accumulation,
    and computes the Spine Age Algorithm.

    Spine Age = BioAge + (SlouchHours × 1.2) - (StretchMinutes × 0.5)
    where:
        SlouchHours   = cumulative seconds with non-'good' label ÷ 3600
        StretchMinutes = cumulative seconds with 'good' label ÷ 60
    """

    BREAK_INTERVAL      = 40 * 60   # seconds between break reminders
    GOOD_STREAK_NOTIFY  = 30 * 60   # notify every 30-min good streak milestone

    def __init__(self, on_break_needed=None, on_good_streak=None):
        self.on_break_needed = on_break_needed
        self.on_good_streak  = on_good_streak

        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.session_start       = datetime.now()
        self.sitting_seconds     = 0
        self.break_seconds       = 0
        self.active_seconds      = 0
        self.breaks_taken        = 0
        self.consecutive_sitting = 0    # seconds since last break
        self.good_streak         = 0    # seconds of consecutive good posture
        self.best_streak         = 0    # longest good_streak seen this session

        # ── Spine Age tracking ────────────────────────────────────────────────
        self.slouch_seconds      = 0    # total seconds with bad/fhp/lateral label
        self.stretch_seconds     = 0    # total seconds with 'good' label

        self._break_alerted      = False
        self._good_notified_at   = 0
        self._scores: list[float] = []
        self._labels: list[str]   = []

    # ── Main tick (called every second from monitor thread) ───────────────────

    def tick(self, is_active: bool, label: str, score: float):
        with self._lock:
            if is_active:
                self.sitting_seconds     += 1
                self.active_seconds      += 1
                self.consecutive_sitting += 1
                self._scores.append(score)
                self._labels.append(label)

                # Accumulate slouch / stretch time
                if label.lower() == 'good':
                    self.stretch_seconds += 1
                    self.good_streak     += 1
                    if self.good_streak > self.best_streak:
                        self.best_streak = self.good_streak

                    # Good streak milestone notification
                    milestone = self.good_streak // self.GOOD_STREAK_NOTIFY
                    if milestone > self._good_notified_at:
                        self._good_notified_at = milestone
                        mins = milestone * (self.GOOD_STREAK_NOTIFY // 60)
                        if self.on_good_streak:
                            threading.Thread(
                                target=self.on_good_streak,
                                args=(mins,), daemon=True
                            ).start()
                else:
                    self.slouch_seconds += 1
                    self.good_streak     = 0
                    self._good_notified_at = 0

                # Break reminder
                if (self.consecutive_sitting >= self.BREAK_INTERVAL
                        and not self._break_alerted):
                    self._break_alerted = True
                    if self.on_break_needed:
                        threading.Thread(
                            target=self.on_break_needed, daemon=True
                        ).start()
            else:
                self.break_seconds += 1
                if self.consecutive_sitting > 0:
                    self.consecutive_sitting = 0
                    self._break_alerted = False
                    self.breaks_taken += 1

    # ── Spine Age Algorithm ───────────────────────────────────────────────────

    def spine_age(self, bio_age: int) -> float:
        """
        SpineAge = BioAge + (SlouchHours × 1.2) - (StretchMinutes × 0.5)
        Clamped to [bio_age - 5, bio_age + 20] for sanity.
        """
        with self._lock:
            slouch_hours   = self.slouch_seconds  / 3600.0
            stretch_mins   = self.stretch_seconds / 60.0

        age = bio_age + (slouch_hours * 1.2) - (stretch_mins * 0.5)
        return round(float(max(bio_age - 5, min(bio_age + 20, age))), 1)

    # ── Stats snapshot ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._lock:
            total    = len(self._labels)
            good     = sum(1 for l in self._labels if l.lower() == 'good')
            good_pct  = round(good / total * 100, 1) if total else 0.0
            avg_score = round(sum(self._scores) / total, 1) if total else 0.0
            return {
                'sitting_seconds':     self.sitting_seconds,
                'break_seconds':       self.break_seconds,
                'active_seconds':      self.active_seconds,
                'breaks_taken':        self.breaks_taken,
                'good_posture_pct':    good_pct,
                'avg_posture_score':   avg_score,
                'consecutive_sitting': self.consecutive_sitting,
                'good_streak_sec':     self.good_streak,
                'best_streak_sec':     self.best_streak,
                'slouch_seconds':      self.slouch_seconds,
                'stretch_seconds':     self.stretch_seconds,
                'total_seconds':       self.sitting_seconds + self.break_seconds,
            }

    # ── Time formatting ───────────────────────────────────────────────────────

    def consecutive_minutes(self) -> int:
        with self._lock:
            return self.consecutive_sitting // 60

    @staticmethod
    def format_hhmm(seconds: int) -> str:
        """Return sitting time in HH:MM format."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h:02d}:{m:02d}"

    @staticmethod
    def formatted_time(seconds: int) -> str:
        """Human-readable short form, e.g. '2h 14m' or '47m'."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        if h:
            return f"{h}h {m}m"
        return f"{m}m"
