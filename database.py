from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from config import DATABASE_PATH

TICKET_COLUMNS = [
    "ticket_id", "created_date", "closed_date", "agency", "agency_name",
    "problem", "problem_detail", "incident_zip", "borough", "status",
    "due_date", "resolution_description", "resolution_action_updated_date",
    "ingested_at"
]


def get_connection() -> sqlite3.Connection:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def initialise_database() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_tickets (
                ticket_id TEXT PRIMARY KEY,
                created_date TEXT,
                closed_date TEXT,
                agency TEXT,
                agency_name TEXT,
                problem TEXT,
                problem_detail TEXT,
                incident_zip TEXT,
                borough TEXT,
                status TEXT,
                due_date TEXT,
                resolution_description TEXT,
                resolution_action_updated_date TEXT,
                ingested_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_worklog (
                ticket_id TEXT PRIMARY KEY,
                assigned_to TEXT,
                priority TEXT,
                notes TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(ticket_id) REFERENCES service_tickets(ticket_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_created ON service_tickets(created_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON service_tickets(status)")


def upsert_tickets(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    initialise_database()
    rows = []
    for _, row in frame.iterrows():
        rows.append((
            str(row["unique_key"]),
            row.get("created_date"), row.get("closed_date"), row.get("agency"),
            row.get("agency_name"), row.get("complaint_type"), row.get("descriptor"),
            row.get("incident_zip"), row.get("borough"), row.get("status"),
            row.get("due_date"), row.get("resolution_description"),
            row.get("resolution_action_updated_date"), row.get("fetched_at")
        ))
    sql = """
        INSERT INTO service_tickets (
            ticket_id, created_date, closed_date, agency, agency_name, problem,
            problem_detail, incident_zip, borough, status, due_date,
            resolution_description, resolution_action_updated_date, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id) DO UPDATE SET
            created_date=excluded.created_date,
            closed_date=excluded.closed_date,
            agency=excluded.agency,
            agency_name=excluded.agency_name,
            problem=excluded.problem,
            problem_detail=excluded.problem_detail,
            incident_zip=excluded.incident_zip,
            borough=excluded.borough,
            status=excluded.status,
            due_date=excluded.due_date,
            resolution_description=excluded.resolution_description,
            resolution_action_updated_date=excluded.resolution_action_updated_date,
            ingested_at=excluded.ingested_at
    """
    with get_connection() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def load_tickets() -> pd.DataFrame:
    initialise_database()
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM service_tickets ORDER BY created_date DESC", conn)


def save_worklog(ticket_id: str, assigned_to: str, priority: str, notes: str) -> None:
    from datetime import datetime, timezone

    initialise_database()
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM service_tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if not exists:
            raise ValueError("Cannot attach a note to a ticket that is not in the local source table.")
        conn.execute("""
            INSERT INTO ticket_worklog(ticket_id, assigned_to, priority, notes, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                assigned_to=excluded.assigned_to,
                priority=excluded.priority,
                notes=excluded.notes,
                updated_at=excluded.updated_at
        """, (ticket_id, assigned_to, priority, notes, datetime.now(timezone.utc).isoformat()))


def get_worklog(ticket_id: str) -> dict[str, Any] | None:
    initialise_database()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM ticket_worklog WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None


def get_ticket_counts_by_category() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT problem, COUNT(*) AS request_count FROM service_tickets "
            "GROUP BY problem ORDER BY request_count DESC", conn
        )


def get_ticket_counts_by_borough() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT borough, COUNT(*) AS request_count FROM service_tickets "
            "GROUP BY borough ORDER BY request_count DESC", conn
        )


initialise_database()
