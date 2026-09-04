from __future__ import annotations

import sqlite3
from typing import Any

from customer_support_agent.core.settings import ensure_directories, get_settings


def connect() -> sqlite3.Connection:
    settings = get_settings()
    ensure_directories(settings)

    conn = sqlite3.connect(str(settings.db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Additive schema changes for DBs created before the multi-round workflow.

    `CREATE TABLE IF NOT EXISTS` cannot add a column to a table that already
    exists, so the columns introduced for the claim lifecycle are added here
    with a guarded ALTER TABLE. Safe to run on every startup.
    """
    if not _column_exists(conn, "tickets", "claim_type"):
        conn.execute("ALTER TABLE tickets ADD COLUMN claim_type TEXT")

    if not _column_exists(conn, "tickets", "lifecycle_stage"):
        conn.execute(
            "ALTER TABLE tickets ADD COLUMN lifecycle_stage TEXT DEFAULT 'intake'"
        )
        # Back-fill: a claim that was already resolved under the old two-state
        # model belongs at the end of the new lifecycle, not the start.
        conn.execute(
            "UPDATE tickets SET lifecycle_stage = 'resolved' "
            "WHERE status = 'resolved' "
            "AND (lifecycle_stage IS NULL OR lifecycle_stage = 'intake')"
        )

    if not _column_exists(conn, "drafts", "kind"):
        conn.execute(
            "ALTER TABLE drafts ADD COLUMN kind TEXT DEFAULT 'intake_request'"
        )

    # Phase 3 - settlement & closure. The claim lifecycle now continues past the
    # coverage recommendation into settlement (decision + repair + payment) and
    # a terminal closed state.
    if not _column_exists(conn, "tickets", "coverage_decision"):
        for ddl in (
            "ALTER TABLE tickets ADD COLUMN coverage_decision TEXT",
            "ALTER TABLE tickets ADD COLUMN decision_note TEXT",
            "ALTER TABLE tickets ADD COLUMN repair_authorized INTEGER DEFAULT 0",
            "ALTER TABLE tickets ADD COLUMN payment_arranged INTEGER DEFAULT 0",
            "ALTER TABLE tickets ADD COLUMN outcome TEXT",
            "ALTER TABLE tickets ADD COLUMN closed_at TIMESTAMP",
        ):
            conn.execute(ddl)
        # A claim that was 'resolved' under Phase 2 was fully done - move it to
        # the new terminal state and assume it was an approval.
        conn.execute(
            "UPDATE tickets SET lifecycle_stage = 'closed', outcome = 'approved', "
            "coverage_decision = 'approved', closed_at = CURRENT_TIMESTAMP "
            "WHERE lifecycle_stage = 'resolved'"
        )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                company TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER REFERENCES customers(id),
                subject TEXT NOT NULL,
                description TEXT NOT NULL,
                claim_type TEXT,
                status TEXT DEFAULT 'open',
                lifecycle_stage TEXT DEFAULT 'intake',
                priority TEXT DEFAULT 'medium',
                coverage_decision TEXT,
                decision_note TEXT,
                repair_authorized INTEGER DEFAULT 0,
                payment_arranged INTEGER DEFAULT 0,
                outcome TEXT,
                closed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER REFERENCES tickets(id),
                content TEXT NOT NULL,
                context_used TEXT,
                kind TEXT DEFAULT 'intake_request',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS claim_requirements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id),
                item_label TEXT NOT NULL,
                category TEXT DEFAULT 'document',
                status TEXT DEFAULT 'needed',
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS claim_correspondence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id),
                direction TEXT NOT NULL,
                channel TEXT DEFAULT 'email',
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TRIGGER IF NOT EXISTS tickets_updated_at_trigger
            AFTER UPDATE ON tickets
            FOR EACH ROW
            BEGIN
                UPDATE tickets
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = OLD.id;
            END;

            CREATE TRIGGER IF NOT EXISTS claim_requirements_updated_at_trigger
            AFTER UPDATE ON claim_requirements
            FOR EACH ROW
            BEGIN
                UPDATE claim_requirements
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = OLD.id;
            END;

            """
        )
        _run_migrations(conn)
