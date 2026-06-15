"""Device profile persistence — Layer 2 server-side fingerprint matching.

Schema: device_profiles(student_id, device_hash, canvas_hash, webgl_renderer,
                        audio_hash, screen_sig, user_agent, ip_address,
                        device_token, device_label, total_seen, first_seen, last_seen)

Each student_id can have up to 5 device profiles.
Exact match: device_hash equality. P1 only — fuzzy matching is P2.
"""
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


class DeviceProfileDB:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS device_profiles (
                    student_id   TEXT NOT NULL,
                    device_hash  TEXT NOT NULL,
                    canvas_hash  TEXT NOT NULL DEFAULT '',
                    webgl_renderer TEXT NOT NULL DEFAULT '',
                    audio_hash   TEXT NOT NULL DEFAULT '',
                    screen_sig   TEXT NOT NULL DEFAULT '',
                    user_agent   TEXT NOT NULL DEFAULT '',
                    ip_address   TEXT NOT NULL DEFAULT '',
                    device_token TEXT NOT NULL DEFAULT '',
                    device_label TEXT NOT NULL DEFAULT '',
                    total_seen   INTEGER NOT NULL DEFAULT 1,
                    first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                    last_seen    TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (student_id, device_hash)
                )
            """)
            # Enforce 5-device limit per student
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS device_profiles_limit
                AFTER INSERT ON device_profiles
                BEGIN
                    DELETE FROM device_profiles
                    WHERE student_id = NEW.student_id
                      AND device_hash NOT IN (
                          SELECT device_hash FROM device_profiles
                          WHERE student_id = NEW.student_id
                          ORDER BY last_seen DESC LIMIT 5
                      );
                END
            """)


    def match_or_create(
        self,
        student_id: str,
        device_hash: str,
        fingerprint: dict,
        user_agent: str,
        ip_address: str,
    ) -> tuple[str | None, bool]:
        """Match device by exact hash, or create new profile.

        Returns (device_token, known_device).
        - known_device=True: exact hash match → existing device
        - known_device=False: no match → new device registered
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            # Exact match
            row = conn.execute(
                "SELECT device_token, total_seen FROM device_profiles "
                "WHERE student_id = ? AND device_hash = ?",
                (student_id, device_hash),
            ).fetchone()

            if row:
                device_token = row[0]
                # Update signals (fingerprint evolution)
                conn.execute(
                    "UPDATE device_profiles SET "
                    "canvas_hash = ?, webgl_renderer = ?, audio_hash = ?, "
                    "screen_sig = ?, user_agent = ?, ip_address = ?, "
                    "total_seen = total_seen + 1, last_seen = ? "
                    "WHERE student_id = ? AND device_hash = ?",
                    (
                        fingerprint.get("canvas_hash", ""),
                        fingerprint.get("webgl_renderer", ""),
                        fingerprint.get("audio_hash", ""),
                        fingerprint.get("screen_sig", ""),
                        user_agent,
                        ip_address,
                        now,
                        student_id,
                        device_hash,
                    ),
                )
                return device_token, True

            # New device
            device_token = secrets.token_hex(16)
            device_label = self._make_label(user_agent, fingerprint)

            conn.execute(
                "INSERT INTO device_profiles "
                "(student_id, device_hash, canvas_hash, webgl_renderer, audio_hash, "
                "screen_sig, user_agent, ip_address, device_token, device_label, "
                "first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    student_id, device_hash,
                    fingerprint.get("canvas_hash", ""),
                    fingerprint.get("webgl_renderer", ""),
                    fingerprint.get("audio_hash", ""),
                    fingerprint.get("screen_sig", ""),
                    user_agent, ip_address,
                    device_token, device_label,
                    now, now,
                ),
            )
            return device_token, False


    @staticmethod
    def _make_label(user_agent: str, fingerprint: dict) -> str:
        """Human-readable device label, e.g. 'Chrome on Mali-G52'."""
        parts = []
        # Browser
        ua = (user_agent or "").lower()
        if "chrome" in ua and "edg" not in ua:
            parts.append("Chrome")
        elif "edg" in ua:
            parts.append("Edge")
        elif "safari" in ua:
            parts.append("Safari")
        elif "firefox" in ua:
            parts.append("Firefox")
        elif "micromessenger" in ua:
            parts.append("WeChat")

        # Renderer
        webgl = fingerprint.get("webgl_renderer", "")
        if webgl:
            parts.append(webgl.split(" ")[0] if " " in webgl else webgl[:20])

        return " on ".join(parts) if parts else "Unknown"
