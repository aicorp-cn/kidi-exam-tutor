"""SQLite persistence for exam records and student users."""
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
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
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
            for col, col_def in [
                ("variant", "TEXT NOT NULL DEFAULT ''"),
                ("passage", "TEXT NOT NULL DEFAULT ''"),
                ("s1_questions", "TEXT NOT NULL DEFAULT ''"),
                ("question_count", "INTEGER NOT NULL DEFAULT 0"),
                ("starred", "INTEGER NOT NULL DEFAULT 0"),
                ("user_id", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE exams ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_session ON exams(session_id)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_created ON exams(created_at DESC)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_type ON exams(exam_type)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_exams_user ON exams(user_id)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_vocab_user ON vocabulary(user_id)""")

            for col, col_def in [("user_id", "TEXT NOT NULL DEFAULT ''")]:
                try:
                    conn.execute(f"ALTER TABLE vocabulary ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS vocabulary (
                    word TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    pos TEXT NOT NULL DEFAULT '',
                    chinese TEXT NOT NULL DEFAULT '',
                    exam_ids TEXT NOT NULL DEFAULT '[]',
                    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                    appearance_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (word, user_id)
                )
            """)

    # ── Exams CRUD ──

    def _check_owner(self, exam_id: str, user_id: str) -> bool:
        """Return True if exam.user_id matches."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT user_id FROM exams WHERE id = ?", (exam_id,)
            ).fetchone()
        return row is not None and row[0] == user_id

    def save(self, *, session_id: str, exam_type: str,
             ocr_text: str, tutorial: str,
             user_id: str = "",
             variant: str = "", passage: str = "",
             s1_questions: str = "", question_count: int = 0,
             warnings: list = None) -> str:
        exam_id = str(uuid.uuid4())[:8]
        warnings_json = json.dumps(warnings or [], ensure_ascii=False)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO exams (id, session_id, user_id, exam_type, variant, "
                "passage, s1_questions, question_count, "
                "ocr_text, tutorial, warnings) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exam_id, session_id, user_id, exam_type, variant,
                 passage, s1_questions, question_count,
                 ocr_text, tutorial, warnings_json),
            )
        return exam_id

    def get_exam(self, exam_id: str, user_id: str = "") -> dict | None:
        if user_id and not self._check_owner(exam_id, user_id):
            return None
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
        return dict(row) if row else None

    def toggle_star(self, exam_id: str, user_id: str = "") -> bool:
        if user_id and not self._check_owner(exam_id, user_id):
            return False
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT starred FROM exams WHERE id = ?", (exam_id,)).fetchone()
            if not row:
                conn.commit(); return False
            new_val = 1 if row[0] == 0 else 0
            conn.execute("UPDATE exams SET starred = ? WHERE id = ?", (new_val, exam_id))
            conn.commit()
        return new_val == 1

    def get_review(self, exam_id: str, user_id: str = "") -> dict | None:
        exam = self.get_exam(exam_id, user_id=user_id)
        if not exam:
            return None
        result = {"exam_id": exam["id"], "exam_type": exam.get("exam_type", ""),
                  "variant": exam.get("variant", ""), "passage": exam.get("passage", "")}
        for field, default in [("tutorial", []), ("s1_questions", []), ("warnings", [])]:
            try:
                result["questions" if field == "tutorial" else field] = json.loads(
                    exam.get(field, "[]"))
            except (json.JSONDecodeError, TypeError):
                result["questions" if field == "tutorial" else field] = default
        result["vocabulary"] = self._vocab_for_exam(exam_id, user_id=user_id)
        return result

    def _vocab_for_exam(self, exam_id: str, user_id: str = "") -> dict:
        from vocab import get_curriculum
        curriculum = get_curriculum()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            extra = "AND user_id = ?" if user_id else ""
            params = ([user_id] if user_id else [])
            rows = conn.execute(
                f"SELECT word, pos, chinese, appearance_count, exam_ids FROM vocabulary "
                f"WHERE 1=1 {extra}", params
            ).fetchall()
        tiers = {"high": [], "medium": [], "low": []}
        for row in rows:
            ids = json.loads(row["exam_ids"])
            if exam_id not in ids:
                continue
            w = row["word"]; count = row["appearance_count"]
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

    def delete_exam(self, exam_id: str, user_id: str = "") -> bool:
        if user_id and not self._check_owner(exam_id, user_id):
            return False
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._clean_vocab_refs(conn, [exam_id])
            cur = conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
            conn.commit()
            return cur.rowcount > 0

    def delete_exams(self, ids: list[str], user_id: str = "") -> int:
        if not ids:
            return 0
        if user_id:
            ids = [eid for eid in ids if self._check_owner(eid, user_id)]
            if not ids:
                return 0
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._clean_vocab_refs(conn, ids)
            placeholders = ",".join("?" for _ in ids)
            cur = conn.execute(f"DELETE FROM exams WHERE id IN ({placeholders})", ids)
            conn.commit()
            return cur.rowcount

    def _clean_vocab_refs(self, conn, exam_ids: list[str]):
        rows = conn.execute(
            "SELECT word, exam_ids, appearance_count FROM vocabulary").fetchall()
        for word, exam_ids_str, count in rows:
            ids = json.loads(exam_ids_str)
            removed = sum(1 for eid in exam_ids if eid in ids)
            if removed == 0:
                continue
            for eid in exam_ids:
                if eid in ids:
                    ids.remove(eid)
            new_count = count - removed
            if new_count <= 0:
                conn.execute("DELETE FROM vocabulary WHERE word = ?", (word,))
            else:
                conn.execute(
                    "UPDATE vocabulary SET exam_ids = ?, appearance_count = ?, "
                    "last_seen = datetime('now') WHERE word = ?",
                    (json.dumps(ids), new_count, word))
        # GC pass
        valid_ids = {r[0] for r in conn.execute("SELECT id FROM exams").fetchall()}
        rows = conn.execute(
            "SELECT word, exam_ids, appearance_count FROM vocabulary").fetchall()
        for word, exam_ids_str, count in rows:
            ids = json.loads(exam_ids_str)
            clean_ids = [eid for eid in ids if eid in valid_ids]
            if len(clean_ids) == len(ids):
                continue
            new_count = count - (len(ids) - len(clean_ids))
            if new_count <= 0:
                conn.execute("DELETE FROM vocabulary WHERE word = ?", (word,))
            else:
                conn.execute(
                    "UPDATE vocabulary SET exam_ids = ?, appearance_count = ?, "
                    "last_seen = datetime('now') WHERE word = ?",
                    (json.dumps(clean_ids), new_count, word))

    def list_exams(self, page: int = 1, limit: int = 20,
                   search: str = "", exam_type: str = "",
                   user_id: str = "") -> tuple[list[dict], int, dict]:
        offset = (page - 1) * limit
        conditions = []
        params = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
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
            type_counts = {}
            tc_cond = "WHERE user_id = ?" if user_id else ""
            tc_params = [user_id] if user_id else []
            tc_rows = conn.execute(
                f"SELECT exam_type, COUNT(*) as cnt FROM exams {tc_cond} GROUP BY exam_type",
                tc_params).fetchall()
            for r in tc_rows:
                if r["exam_type"]:
                    type_counts[r["exam_type"]] = r["cnt"]
        return [dict(r) for r in rows], total, type_counts

    # ── Vocabulary ──

    def vocab_lookup(self, words: list[str], user_id: str = "") -> dict[str, dict]:
        if not words:
            return {}
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" for _ in words)
            extra = "AND user_id = ?" if user_id else ""
            params = words + ([user_id] if user_id else [])
            rows = conn.execute(
                f"SELECT word, pos, chinese, exam_ids, first_seen, appearance_count "
                f"FROM vocabulary WHERE word IN ({placeholders}) {extra}", params).fetchall()
        return {r["word"]: dict(r) for r in rows}

    def vocab_record(self, word: str, pos: str, chinese: str, exam_id: str,
                     user_id: str = ""):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO vocabulary (word, pos, chinese, exam_ids, appearance_count, user_id) "
                "VALUES (?, ?, ?, ?, 1, ?) "
                "ON CONFLICT(word, user_id) DO UPDATE SET "
                "exam_ids = CASE WHEN ? NOT IN (SELECT value FROM json_each(vocabulary.exam_ids)) "
                "THEN json_insert(vocabulary.exam_ids, '$[#]', ?) ELSE vocabulary.exam_ids END, "
                "appearance_count = vocabulary.appearance_count + "
                "CASE WHEN ? NOT IN (SELECT value FROM json_each(vocabulary.exam_ids)) THEN 1 ELSE 0 END, "
                "last_seen = datetime('now')",
                (word, pos, chinese, json.dumps([exam_id]), user_id,
                 exam_id, exam_id, exam_id))
            conn.commit()
