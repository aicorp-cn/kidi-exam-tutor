"""Student identity system built on fastapi-users.

Student ID encoding: {province}-{city}-{gender}-{name_init}-{input_id}
Email: {student_id}@aikidi.com (auto-generated, student never sees)
"""
import uuid
import dataclasses
import sqlite3
from pathlib import Path
from typing import Any

import bcrypt
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, models, schemas, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import BaseUserDatabase

# ── Secrets ──
import os
import secrets
AUTH_SECRET = os.getenv("EXAM_TUTOR_JWT_SECRET") or secrets.token_urlsafe(32)

# ── Student model ──

@dataclasses.dataclass
class Student:
    id: uuid.UUID
    email: str
    hashed_password: str
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = True
    student_id: str = ""
    name: str = ""

# ── Schemas ──

class StudentRead(schemas.BaseUser[uuid.UUID]):
    student_id: str
    name: str

class StudentCreate(schemas.BaseUserCreate):
    student_id: str = ""
    name: str = ""

# ── DB adapter ──

class StudentDB(BaseUserDatabase[Student, uuid.UUID]):
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._init()

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def _init(self):
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL DEFAULT '',
                student_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")

    async def get(self, id: uuid.UUID) -> Student | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM users WHERE id = ?", (str(id),)).fetchone()
        return _row_to_student(row)

    async def get_by_email(self, email: str) -> Student | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return _row_to_student(row)

    async def get_by_student_id(self, student_id: str) -> Student | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM users WHERE student_id = ?", (student_id,)).fetchone()
        return _row_to_student(row)

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> Student | None:
        return None

    async def create(self, create_dict: dict[str, Any]) -> Student:
        uid = create_dict.get("id") or str(uuid.uuid4())
        email = create_dict.get("email", "")
        student_id = create_dict.get("student_id", "")
        name = create_dict.get("name", "")
        hashed_password = create_dict.get("hashed_password", "")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, email, hashed_password, student_id, name) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, email, hashed_password, student_id, name),
            )
        return Student(id=uuid.UUID(uid), email=email, student_id=student_id, name=name,
                       hashed_password=hashed_password)

    async def update(self, user: Student, update_dict: dict[str, Any]) -> Student:
        sets = []
        vals = []
        for k in ("student_id", "name", "hashed_password"):
            if k in update_dict:
                sets.append(f"{k} = ?")
                vals.append(update_dict[k])
        if sets:
            vals.append(str(user.id))
            with self._connect() as conn:
                conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", vals)
            for k in ("student_id", "name", "hashed_password"):
                if k in update_dict:
                    setattr(user, k, update_dict[k])
        return user

    async def delete(self, user: Student) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (str(user.id),))


def _row_to_student(row: sqlite3.Row | None) -> Student | None:
    if row is None:
        return None
    return Student(
        id=uuid.UUID(row["id"]),
        email=row["email"],
        hashed_password=row["hashed_password"],
        student_id=row["student_id"],
        name=row["name"],
    )


# ── UserManager ──

class StudentManager(UUIDIDMixin, BaseUserManager[Student, uuid.UUID]):
    async def validate_password(self, password: str, user) -> None:
        if password and len(password) < 6:
            from fastapi_users import exceptions
            raise exceptions.InvalidPasswordException(reason="密码至少6位")

    async def on_after_register(self, user: Student, request: Request | None = None):
        pass


# ── Dependencies ──

_student_db: StudentDB | None = None

def init_student_db(db_path: str) -> StudentDB:
    global _student_db
    _student_db = StudentDB(db_path)
    return _student_db

async def get_user_db():
    yield _student_db

async def get_user_manager(user_db: StudentDB = Depends(get_user_db)):
    yield StudentManager(user_db)


# ── Auth backend + FastAPIUsers ──

bearer_transport = BearerTransport(tokenUrl="/auth/jwt/login")

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=AUTH_SECRET, lifetime_seconds=86400 * 7)

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

def create_fastapi_users(get_user_manager_dep, auth_backends):
    return FastAPIUsers[Student, uuid.UUID](get_user_manager_dep, auth_backends)
