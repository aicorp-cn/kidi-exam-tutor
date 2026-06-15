"""Device profile persistence — Layer 2 server-side fingerprint matching.

Schema: device_profiles(student_id, device_hash, canvas_hash, webgl_renderer,
                        screen_sig, user_agent, ip_address,
                        device_token, device_label, total_seen, first_seen, last_seen)

Each student_id can have up to 5 device profiles.
P1: Exact match on device_hash. P2: Fuzzy match with fingerprint evolution.
"""
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass

# ── Fuzzy match signal weights (P2) ──────────────────────────────────────────
# user_agent 权重为 0：浏览器版本太易变，零信号价值
SIGNAL_WEIGHTS = {
    "webgl_renderer": 0.70,
    "ip_network":     0.15,
    "device_hash":    0.10,
}
FUZZY_THRESHOLD = 0.5


@dataclass
class FuzzyResult:
    device_hash: str
    score: float
    device_token: str
    total_seen: int
    first_seen: str


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


    def _get_all_profiles(self, conn: sqlite3.Connection, student_id: str
                          ) -> list[dict]:
        rows = conn.execute(
            "SELECT device_hash, webgl_renderer, ip_address, device_token, "
            "total_seen, first_seen FROM device_profiles WHERE student_id=?",
            (student_id,),
        ).fetchall()
        return [
            dict(zip(
                ["device_hash", "webgl_renderer", "ip_address",
                 "device_token", "total_seen", "first_seen"],
                row,
            ))
            for row in rows
        ]


    @staticmethod
    def fuzzy_match(
        fingerprint: dict,
        ip_address: str,
        profiles: list[dict],
    ) -> FuzzyResult | None:
        """Weighted fuzzy match against all profiles for a student.

        Returns the best match if score >= FUZZY_THRESHOLD, else None.
        """
        best = None
        req_ip_parts = ip_address.split(".") if ip_address else []

        for p in profiles:
            score = 0.0

            # WebGL renderer: exact match → strongest signal
            if fingerprint.get("webgl_renderer") == p["webgl_renderer"]:
                score += SIGNAL_WEIGHTS["webgl_renderer"]

            # IP /24 subnet match
            prof_ip_parts = (p.get("ip_address") or "").split(".")
            if (
                len(req_ip_parts) == 4
                and len(prof_ip_parts) == 4
                and req_ip_parts[:3] == prof_ip_parts[:3]
            ):
                score += SIGNAL_WEIGHTS["ip_network"]

            # device_hash (exact — only relevant if outer exact match missed
            # due to concurrency; defensive)
            if fingerprint.get("device_hash") == p["device_hash"]:
                score += SIGNAL_WEIGHTS["device_hash"]

            if best is None or score > best.score:
                best = FuzzyResult(
                    device_hash=p["device_hash"],
                    score=score,
                    device_token=p["device_token"],
                    total_seen=p["total_seen"],
                    first_seen=p["first_seen"],
                )

        if best is not None and best.score >= FUZZY_THRESHOLD:
            return best
        return None


    def match_or_create(
        self,
        student_id: str,
        device_hash: str,
        fingerprint: dict,
        user_agent: str,
        ip_address: str,
    ) -> tuple[str | None, bool]:
        """Match device: exact hash → fuzzy → create new.

        Returns (device_token, known_device).
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            # ── P1: Exact match ──────────────────────────────────────
            row = conn.execute(
                "SELECT device_token, total_seen FROM device_profiles "
                "WHERE student_id = ? AND device_hash = ?",
                (student_id, device_hash),
            ).fetchone()

            if row:
                device_token = row[0]
                conn.execute(
                    "UPDATE device_profiles SET "
                    "canvas_hash = ?, webgl_renderer = ?, "
                    "screen_sig = ?, user_agent = ?, ip_address = ?, "
                    "total_seen = total_seen + 1, last_seen = ? "
                    "WHERE student_id = ? AND device_hash = ?",
                    (
                        fingerprint.get("canvas_hash", ""),
                        fingerprint.get("webgl_renderer", ""),
                        fingerprint.get("screen_sig", ""),
                        user_agent,
                        ip_address,
                        now,
                        student_id,
                        device_hash,
                    ),
                )
                return device_token, True

            # ── P2: Fuzzy match ──────────────────────────────────────
            profiles = self._get_all_profiles(conn, student_id)
            best = self.fuzzy_match(fingerprint, ip_address, profiles)

            if best is not None:
                # Fingerprint evolution: replace old hash with new hash,
                # inherit device_token + label + history.
                old = conn.execute(
                    "SELECT device_label FROM device_profiles "
                    "WHERE student_id = ? AND device_hash = ?",
                    (student_id, best.device_hash),
                ).fetchone()
                label = old[0] if old else self._make_label(user_agent, fingerprint)

                conn.execute(
                    "DELETE FROM device_profiles "
                    "WHERE student_id = ? AND device_hash = ?",
                    (student_id, best.device_hash),
                )
                conn.execute(
                    "INSERT INTO device_profiles "
                    "(student_id, device_hash, canvas_hash, webgl_renderer, "
                    "screen_sig, user_agent, ip_address, device_token, "
                    "device_label, total_seen, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        student_id, device_hash,
                        fingerprint.get("canvas_hash", ""),
                        fingerprint.get("webgl_renderer", ""),
                        fingerprint.get("screen_sig", ""),
                        user_agent, ip_address,
                        best.device_token, label,
                        best.total_seen + 1, best.first_seen, now,
                    ),
                )
                return best.device_token, True

            # ── New device ───────────────────────────────────────────
            device_token = secrets.token_hex(16)
            device_label = self._make_label(user_agent, fingerprint)

            conn.execute(
                "INSERT INTO device_profiles "
                "(student_id, device_hash, canvas_hash, webgl_renderer, "
                "screen_sig, user_agent, ip_address, device_token, device_label, "
                "first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    student_id, device_hash,
                    fingerprint.get("canvas_hash", ""),
                    fingerprint.get("webgl_renderer", ""),
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

        webgl = fingerprint.get("webgl_renderer", "")
        if webgl:
            parts.append(webgl.split(" ")[0] if " " in webgl else webgl[:20])

        return " on ".join(parts) if parts else "Unknown"
