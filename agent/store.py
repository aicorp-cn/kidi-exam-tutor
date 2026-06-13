"""SQLite persistence for exam records."""

import sqlite3
import uuid
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
                    starred INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Migration: add columns missing from older schemas
            for col, col_def in [
                ("variant", "TEXT NOT NULL DEFAULT ''"),
                ("passage", "TEXT NOT NULL DEFAULT ''"),
                ("s1_questions", "TEXT NOT NULL DEFAULT ''"),
                ("question_count", "INTEGER NOT NULL DEFAULT 0"),
                ("starred", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE exams ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_session ON exams(session_id)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_created ON exams(created_at DESC)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_type ON exams(exam_type)""")

            # Vocabulary tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vocabulary (
                    word TEXT PRIMARY KEY,
                    pos TEXT NOT NULL DEFAULT '',
                    chinese TEXT NOT NULL DEFAULT '',
                    exam_ids TEXT NOT NULL DEFAULT '[]',
                    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                    appearance_count INTEGER NOT NULL DEFAULT 0
                )
            """)

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

    def toggle_star(self, exam_id: str) -> bool:
        """Toggle starred status. Returns new state (True=starred)."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT starred FROM exams WHERE id = ?", (exam_id,)
            ).fetchone()
            if not row:
                conn.commit()
                return False
            new_val = 1 if row[0] == 0 else 0
            conn.execute(
                "UPDATE exams SET starred = ? WHERE id = ?", (new_val, exam_id)
            )
            conn.commit()
        return new_val == 1

    def get_review(self, exam_id: str) -> dict | None:
        """Return full review data with vocabulary insight.

        Single source of truth for review data — used by both SSE (new exams)
        and API (history replay). Returns None if exam not found.
        """
        exam = self.get_exam(exam_id)
        if not exam:
            return None

        result = {
            "exam_id": exam["id"],
            "exam_type": exam.get("exam_type", ""),
            "variant": exam.get("variant", ""),
            "passage": exam.get("passage", ""),
        }

        # Deserialize JSON fields
        for field, default in [("tutorial", []), ("s1_questions", []), ("warnings", [])]:
            try:
                result["questions" if field == "tutorial" else field] = json.loads(exam.get(field, "[]"))
            except (json.JSONDecodeError, TypeError):
                result["questions" if field == "tutorial" else field] = default

        result["vocabulary"] = self._vocab_for_exam(exam_id)
        return result

    def _vocab_for_exam(self, exam_id: str) -> dict:
        """Build vocabulary tiers for a specific exam from stored data."""
        from vocab import get_curriculum
        curriculum = get_curriculum()

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT word, pos, chinese, appearance_count, exam_ids FROM vocabulary"
            ).fetchall()

        tiers = {"high": [], "medium": [], "low": []}
        for row in rows:
            ids = json.loads(row["exam_ids"])
            if exam_id not in ids:
                continue

            w = row["word"]
            count = row["appearance_count"]
            # Stored count already includes this exam — use directly

            if w in curriculum:
                cur = curriculum[w]
                entry = {"word": w, "pos": cur[0], "chinese": cur[1], "count": count}
                tier_key = "high" if count >= 3 else "medium"
            else:
                entry = {"word": w, "pos": row["pos"], "chinese": row["chinese"], "count": count}
                tier_key = "medium" if count >= 2 else "low"

            tiers[tier_key].append(entry)

        for tier in tiers.values():
            tier.sort(key=lambda x: x["word"])
        return tiers

    def delete_exam(self, exam_id: str) -> bool:
        """Delete a single exam and clean vocabulary references. Returns True if deleted."""
        with sqlite3.connect(str(self.db_path)) as conn:
            self._clean_vocab_refs(conn, [exam_id])
            cur = conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
            return cur.rowcount > 0

    def delete_exams(self, ids: list[str]) -> int:
        """Delete multiple exams and clean vocabulary references. Returns count deleted."""
        if not ids:
            return 0
        with sqlite3.connect(str(self.db_path)) as conn:
            self._clean_vocab_refs(conn, ids)
            placeholders = ",".join("?" for _ in ids)
            cur = conn.execute(
                f"DELETE FROM exams WHERE id IN ({placeholders})", ids
            )
            return cur.rowcount

    def _clean_vocab_refs(self, conn, exam_ids: list[str]):
        """Remove exam references from vocabulary table. Deletes words with zero remaining appearances."""
        rows = conn.execute(
            "SELECT word, exam_ids, appearance_count FROM vocabulary"
        ).fetchall()
        for word, exam_ids_str, count in rows:
            ids = json.loads(exam_ids_str)
            removed = 0
            for eid in exam_ids:
                if eid in ids:
                    ids.remove(eid)
                    removed += 1
            if removed == 0:
                continue
            new_count = count - removed
            if new_count <= 0:
                conn.execute("DELETE FROM vocabulary WHERE word = ?", (word,))
            else:
                conn.execute(
                    "UPDATE vocabulary SET exam_ids = ?, appearance_count = ?, "
                    "last_seen = datetime('now') WHERE word = ?",
                    (json.dumps(ids), new_count, word),
                )

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
                f"s1_questions, question_count, starred, created_at FROM exams "
                f"{where} ORDER BY starred DESC, created_at DESC LIMIT ? OFFSET ?",
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

    # ── Vocabulary ──

    def vocab_lookup(self, words: list[str]) -> dict[str, dict]:
        """Return appearance history for a list of lowercase words.
        Returns {word: {appearance_count, exam_ids, first_seen} | None}.
        """
        if not words:
            return {}
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" for _ in words)
            rows = conn.execute(
                f"SELECT word, pos, chinese, exam_ids, first_seen, appearance_count "
                f"FROM vocabulary WHERE word IN ({placeholders})",
                words,
            ).fetchall()
        return {r["word"]: dict(r) for r in rows}

    def vocab_record(self, word: str, pos: str, chinese: str, exam_id: str):
        """Record a word's appearance in an exam. Atomic upsert via transaction."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT exam_ids, appearance_count FROM vocabulary WHERE word = ?",
                (word,),
            ).fetchone()
            if row:
                ids = json.loads(row[0])
                if exam_id not in ids:
                    ids.append(exam_id)
                conn.execute(
                    "UPDATE vocabulary SET exam_ids=?, appearance_count=?, "
                    "last_seen=datetime('now') WHERE word=?",
                    (json.dumps(ids), row[1] + 1, word),
                )
            else:
                conn.execute(
                    "INSERT INTO vocabulary (word, pos, chinese, exam_ids, appearance_count) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (word, pos, chinese, json.dumps([exam_id])),
                )
            conn.commit()
