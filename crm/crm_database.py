"""
crm_database.py
===============

Ядро CRM: SQLite-модели, инициализация таблиц и CRUD-операции.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# =====================================================================
#  Data classes (модели таблиц)
# =====================================================================

@dataclass
class Client:
    id: Optional[int] = None
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    email: str = ""
    status: str = "active"            # active / archived
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Deal:
    id: Optional[int] = None
    client_id: Optional[int] = None    # nullable — сделка может быть без клиента
    title: str = ""
    description: str = ""
    status: str = "new"                # new / in_progress / closed / cancelled
    amount: float = 0.0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Task:
    id: Optional[int] = None
    client_id: Optional[int] = None    # nullable
    deal_id: Optional[int] = None      # nullable
    title: str = ""
    description: str = ""
    status: str = "pending"            # pending / in_progress / completed
    priority: str = "normal"           # low / normal / high
    due_date: str = ""                 # ISO-дата
    created_at: str = ""


# =====================================================================
#  Helpers
# =====================================================================

def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _to_db(obj) -> dict:
    """Превращаем dataclass в словарь для INSERT/UPDATE."""
    return {k: v for k, v in obj.__dict__.items() if k != "id" and v is not None}


# =====================================================================
#  CRUD Engine
# =====================================================================

class CRUDEngine:
    """Обёртка над SQLite3 с полным набором CRUD-операций CRM."""

    # ---------------------------------------------------------------- SQL
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS clients (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name  TEXT NOT NULL DEFAULT '',
        last_name   TEXT NOT NULL DEFAULT '',
        phone       TEXT NOT NULL DEFAULT '',
        email       TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'active',
        notes       TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS deals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id   INTEGER REFERENCES clients(id) ON DELETE SET NULL,
        title       TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'new',
        amount      REAL NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id   INTEGER REFERENCES clients(id) ON DELETE SET NULL,
        deal_id     INTEGER REFERENCES deals(id) ON DELETE SET NULL,
        title       TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'pending',
        priority    TEXT NOT NULL DEFAULT 'normal',
        due_date    TEXT,
        created_at  TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_deals_client_id ON deals(client_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_client_id ON tasks(client_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_deal_id   ON tasks(deal_id);
    """

    # ---------------------------------------------------------------- init
    def __init__(self, db_path: str = "crm.db") -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self.connect()

    # ---------------------------------------------------------------- connect
    def connect(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # --------------------------------------------------------- context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ================================================================ CLIENTS

    def create_client(self, client: Client) -> Client:
        now = _now()
        client.created_at = now
        client.updated_at = now
        cur = self._conn.execute(
            "INSERT INTO clients (first_name, last_name, phone, email, status, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (client.first_name, client.last_name, client.phone,
             client.email, client.status, client.notes, now, now)
        )
        self._conn.commit()
        client.id = cur.lastrowid
        return client

    def get_client(self, client_id: int) -> Optional[Client]:
        row = self._conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return self._row_to_client(row) if row else None

    def list_clients(self, *, status: Optional[str] = None,
                     search: Optional[str] = None,
                     limit: int = 100, offset: int = 0) -> list[Client]:
        sql = "SELECT * FROM clients WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if search:
            pattern = f"%{search}%"
            sql += " AND (first_name LIKE ? ESCAPE '\\' OR last_name LIKE ? ESCAPE '\\' " \
                   "OR phone LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\')"
            params.extend([pattern, pattern, pattern, pattern])
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_client(r) for r in rows]

    def update_client(self, client_id: int, **fields) -> Optional[Client]:
        if not fields:
            return self.get_client(client_id)
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [client_id]
        self._conn.execute(
            f"UPDATE clients SET {sets} WHERE id = ?", values
        )
        self._conn.commit()
        return self.get_client(client_id)

    def archive_client(self, client_id: int) -> Optional[Client]:
        return self.update_client(client_id, status="archived")

    def delete_client(self, client_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ================================================================ DEALS

    def create_deal(self, deal: Deal) -> Deal:
        now = _now()
        deal.created_at = now
        deal.updated_at = now
        self._conn.execute(
            "INSERT INTO deals (client_id, title, description, status, amount, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (deal.client_id, deal.title, deal.description,
             deal.status, deal.amount, now, now)
        )
        self._conn.commit()
        deal.id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return deal

    def get_deal(self, deal_id: int) -> Optional[Deal]:
        row = self._conn.execute(
            "SELECT * FROM deals WHERE id = ?", (deal_id,)
        ).fetchone()
        return self._row_to_deal(row) if row else None

    def list_deals(self, *, client_id: Optional[int] = None,
                   status: Optional[str] = None,
                   search: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> list[Deal]:
        sql = "SELECT * FROM deals WHERE 1=1"
        params: list = []
        if client_id:
            sql += " AND client_id = ?"
            params.append(client_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if search:
            pattern = f"%{search}%"
            sql += " AND (title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
            params.extend([pattern, pattern])
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_deal(r) for r in rows]

    def update_deal(self, deal_id: int, **fields) -> Optional[Deal]:
        if not fields:
            return self.get_deal(deal_id)
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [deal_id]
        self._conn.execute(
            f"UPDATE deals SET {sets} WHERE id = ?", values
        )
        self._conn.commit()
        return self.get_deal(deal_id)

    def delete_deal(self, deal_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ================================================================ TASKS

    def create_task(self, task: Task) -> Task:
        now = _now()
        task.created_at = now
        self._conn.execute(
            "INSERT INTO tasks (client_id, deal_id, title, description, status, priority, due_date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task.client_id, task.deal_id, task.title, task.description,
             task.status, task.priority, task.due_date, now)
        )
        self._conn.commit()
        task.id = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, *, client_id: Optional[int] = None,
                   deal_id: Optional[int] = None,
                   status: Optional[str] = None,
                   search: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> list[Task]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if client_id:
            sql += " AND client_id = ?"
            params.append(client_id)
        if deal_id:
            sql += " AND deal_id = ?"
            params.append(deal_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if search:
            pattern = f"%{search}%"
            sql += " AND (title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
            params.extend([pattern, pattern])
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_task(self, task_id: int, **fields) -> Optional[Task]:
        if not fields:
            return self.get_task(task_id)
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [task_id]
        self._conn.execute(
            f"UPDATE tasks SET {sets} WHERE id = ?", values
        )
        self._conn.commit()
        return self.get_task(task_id)

    def complete_task(self, task_id: int) -> Optional[Task]:
        return self.update_task(task_id, status="completed")

    def delete_task(self, task_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ============================================================= Mappers

    @staticmethod
    def _row_to_client(row: sqlite3.Row) -> Client:
        return Client(
            id=row["id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            phone=row["phone"],
            email=row["email"],
            status=row["status"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_deal(row: sqlite3.Row) -> Deal:
        return Deal(
            id=row["id"],
            client_id=row["client_id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            amount=row["amount"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            client_id=row["client_id"],
            deal_id=row["deal_id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            priority=row["priority"],
            due_date=row["due_date"],
            created_at=row["created_at"],
        )
