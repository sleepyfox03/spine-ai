# database/db_manager.py
import sqlite3
import os
from datetime import datetime, date

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, BASE_DIR


class DatabaseManager:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                total_sitting_sec INTEGER DEFAULT 0,
                total_active_sec INTEGER DEFAULT 0,
                total_break_sec INTEGER DEFAULT 0,
                avg_posture_score REAL DEFAULT 0,
                good_posture_pct REAL DEFAULT 0,
                breaks_taken INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS posture_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                timestamp TEXT NOT NULL,
                score REAL,
                label TEXT,
                neck_angle REAL,
                shoulder_tilt REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS eye_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                timestamp TEXT,
                blink_rate REAL,
                screen_distance_cm REAL,
                strain_score REAL
            );
            CREATE TABLE IF NOT EXISTS user_profile (
                id INTEGER PRIMARY KEY,
                name TEXT DEFAULT 'User',
                age INTEGER DEFAULT 25,
                avatar_path TEXT,
                calibration_date TEXT,
                goal_sitting_limit_hrs REAL DEFAULT 6.0,
                goal_breaks_per_day INTEGER DEFAULT 8
            );
        ''')
        self.conn.commit()

    # ── Session ───────────────────────────────────────────────────────────────

    def start_session(self):
        now = datetime.now()
        c = self.conn.execute(
            "INSERT INTO sessions (date, start_time) VALUES (?, ?)",
            (date.today().isoformat(), now.isoformat())
        )
        self.conn.commit()
        return c.lastrowid

    def update_session(self, session_id, stats: dict):
        self.conn.execute('''
            UPDATE sessions SET
                end_time=?, total_sitting_sec=?, total_active_sec=?,
                total_break_sec=?, avg_posture_score=?, good_posture_pct=?, breaks_taken=?
            WHERE id=?
        ''', (
            datetime.now().isoformat(),
            stats.get('sitting_seconds', 0),
            stats.get('active_seconds', 0),
            stats.get('break_seconds', 0),
            stats.get('avg_posture_score', 0),
            stats.get('good_posture_pct', 0),
            stats.get('breaks_taken', 0),
            session_id
        ))
        self.conn.commit()

    def get_today_session(self):
        c = self.conn.execute(
            "SELECT * FROM sessions WHERE date=? ORDER BY id DESC LIMIT 1",
            (date.today().isoformat(),)
        )
        return c.fetchone()

    # ── Posture Records ───────────────────────────────────────────────────────

    def save_posture_record(self, session_id, timestamp, score, label, neck_angle, shoulder_tilt):
        self.conn.execute(
            "INSERT INTO posture_records (session_id, timestamp, score, label, neck_angle, shoulder_tilt) VALUES (?,?,?,?,?,?)",
            (session_id, timestamp, score, label, neck_angle, shoulder_tilt)
        )
        self.conn.commit()

    def get_today_posture_stats(self):
        today = date.today().isoformat()
        rows = self.conn.execute('''
            SELECT pr.label, COUNT(*) AS cnt, AVG(pr.score) AS avg_score
            FROM posture_records pr
            JOIN sessions s ON pr.session_id = s.id
            WHERE s.date = ?
            GROUP BY pr.label
        ''', (today,)).fetchall()

        total = sum(r['cnt'] for r in rows)
        if total == 0:
            return {'good_pct': 0.0, 'avg_score': 0.0, 'total_records': 0}

        good_count = sum(r['cnt'] for r in rows if r['label'] == 'good')
        avg_score = sum(r['avg_score'] * r['cnt'] for r in rows) / total
        return {
            'good_pct': round(good_count / total * 100, 1),
            'avg_score': round(avg_score, 1),
            'total_records': total
        }

    def get_posture_timeline(self, hours=8):
        from datetime import timedelta
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        return self.conn.execute(
            "SELECT timestamp, score, label FROM posture_records WHERE timestamp >= ? ORDER BY timestamp",
            (since,)
        ).fetchall()

    def get_weekly_posture_avg(self):
        return self.conn.execute('''
            SELECT date, AVG(good_posture_pct) AS avg_good
            FROM sessions
            GROUP BY date
            ORDER BY date DESC
            LIMIT 7
        ''').fetchall()

    # ── Eye Records ───────────────────────────────────────────────────────────

    def save_eye_record(self, session_id, timestamp, blink_rate, screen_distance_cm, strain_score):
        self.conn.execute(
            "INSERT INTO eye_records (session_id, timestamp, blink_rate, screen_distance_cm, strain_score) VALUES (?,?,?,?,?)",
            (session_id, timestamp, blink_rate, screen_distance_cm, strain_score)
        )
        self.conn.commit()

    def get_today_eye_stats(self):
        today = date.today().isoformat()
        row = self.conn.execute('''
            SELECT AVG(er.blink_rate) AS avg_blink, AVG(er.strain_score) AS avg_strain,
                   AVG(er.screen_distance_cm) AS avg_dist
            FROM eye_records er
            JOIN sessions s ON er.session_id = s.id
            WHERE s.date = ?
        ''', (today,)).fetchone()
        return dict(row) if row else {}

    # ── User Profile ──────────────────────────────────────────────────────────

    def get_profile(self):
        row = self.conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        return dict(row) if row else None

    def save_profile(self, name='User', age=25, goal_hrs=6.0, goal_breaks=8):
        self.conn.execute('''
            INSERT OR REPLACE INTO user_profile (id, name, age, goal_sitting_limit_hrs, goal_breaks_per_day)
            VALUES (1, ?, ?, ?, ?)
        ''', (name, age, goal_hrs, goal_breaks))
        self.conn.commit()

    def mark_calibrated(self):
        self.conn.execute(
            "INSERT OR IGNORE INTO user_profile (id) VALUES (1)"
        )
        self.conn.execute(
            "UPDATE user_profile SET calibration_date=? WHERE id=1",
            (datetime.now().isoformat(),)
        )
        self.conn.commit()

    # ── Convenience ──────────────────────────────────────────────────────────

    @staticmethod
    def is_calibrated():
        path = os.path.join(BASE_DIR, "calibration_profile.json")
        return os.path.exists(path)


db = DatabaseManager()
