"""SQLite persistence for exam records."""

import sqlite3
import uuid
import time
import json
from pathlib import Path


class ExamStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exams (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    exam_type TEXT NOT NULL DEFAULT '',
                    variant TEXT NOT NULL DEFAULT '',
                    passage TEXT NOT NULL DEFAULT '',
                    s1_questions TEXT NOT NULL DEFAULT '',
                    question_count INTEGER NOT NULL DEFAULT 0,
                    ocr_text TEXT NOT NULL DEFAULT '',
                    tutorial TEXT NOT NULL DEFAULT '',
                    warnings TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Migrations for existing DBs
            for col in ("variant", "passage", "s1_questions", "question_count"):
                try:
                    conn.execute(f"ALTER TABLE exams ADD COLUMN {col} "
                                 f"{'TEXT NOT NULL DEFAULT ' + chr(39) + chr(39) if col != 'question_count' else 'INTEGER NOT NULL DEFAULT 0'}")
                except sqlite3.OperationalError:
                    pass
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_exams_session
                ON exams(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_exams_created
                ON exams(created_at DESC)
            """)

    def save(self, *, session_id: str, exam_type: str,
             ocr_text: str, tutorial: str,
             variant: str = "", passage: str = "",
             s1_questions: str = "", question_count: int = 0,
             warnings: list = None) -> str:
        """Save exam result. Returns the generated exam_id."""
        exam_id = str(uuid.uuid4())[:8]
        warnings_json = json.dumps(warnings or [], ensure_ascii=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO exams (id, session_id, exam_type, variant, "
                "passage, s1_questions, question_count, "
                "ocr_text, tutorial, warnings) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exam_id, session_id, exam_type, variant,
                 passage, s1_questions, question_count,
                 ocr_text, tutorial, warnings_json),
            )
        return exam_id

    def get_exam(self, exam_id: str) -> dict | None:
        """Get a single exam record by ID."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM exams WHERE id = ?", (exam_id,)
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_exams(self, page: int = 1, limit: int = 20) -> tuple[list[dict], int]:
        """List recent exams with pagination. Returns (items, total)."""
        offset = (page - 1) * limit
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0]
            rows = conn.execute(
                "SELECT id, session_id, exam_type, variant, passage, "
                "s1_questions, question_count, created_at FROM exams "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows], total
