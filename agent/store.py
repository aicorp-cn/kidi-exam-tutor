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
            for col in ("variant", "passage", "s1_questions", "question_count"):
                try:
                    conn.execute(f"ALTER TABLE exams ADD COLUMN {col} "
                                 f"{'TEXT NOT NULL DEFAULT ' + chr(39) + chr(39) if col != 'question_count' else 'INTEGER NOT NULL DEFAULT 0'}")
                except sqlite3.OperationalError:
                    pass
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_session ON exams(session_id)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_created ON exams(created_at DESC)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_type ON exams(exam_type)""")

    def save(self, *, session_id: str, exam_type: str,
             ocr_text: str, tutorial: str,
             variant: str = "", passage: str = "",
             s1_questions: str = "", question_count: int = 0,
             warnings: list = None) -> str:
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
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM exams WHERE id = ?", (exam_id,)
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_exams(self, page: int = 1, limit: int = 20,
                   search: str = "", exam_type: str = "") -> tuple[list[dict], int, dict]:
        """List recent exams with optional search and type filter.
        Returns (items, total, type_counts).
        """
        offset = (page - 1) * limit
        conditions = []
        params = []

        if exam_type:
            conditions.append("exam_type = ?")
            params.append(exam_type)

        if search:
            like = f"%{search}%"
            conditions.append("(passage LIKE ? OR ocr_text LIKE ? OR tutorial LIKE ?)")
            params.extend([like, like, like])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        count_sql = f"SELECT COUNT(*) FROM exams {where}"

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(count_sql, params).fetchone()[0]

            rows = conn.execute(
                f"SELECT id, session_id, exam_type, variant, passage, "
                f"s1_questions, question_count, created_at FROM exams "
                f"{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

            # Type counts for filters
            type_counts = {}
            tc_rows = conn.execute(
                "SELECT exam_type, COUNT(*) as cnt FROM exams GROUP BY exam_type"
            ).fetchall()
            for r in tc_rows:
                if r["exam_type"]:
                    type_counts[r["exam_type"]] = r["cnt"]

        return [dict(r) for r in rows], total, type_counts
