from __future__ import annotations

from typing import Any

from customer_support_agent.repositories.sqlite.base import connect, row_to_dict

class TicketsRepository:
    def create(
        self,
        customer_id: int,
        subject: str,
        description: str,
        priority: str = "medium",
        status: str = "open",
        claim_type: str | None = None,
        lifecycle_stage: str = "intake",
    ) -> dict[str, Any]:
        with connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tickets
                    (customer_id, subject, description, priority, status,
                     claim_type, lifecycle_stage)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    subject,
                    description,
                    priority,
                    status,
                    claim_type,
                    lifecycle_stage,
                ),
            )
            ticket_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            return row_to_dict(row) or {}

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.*,
                    c.email AS customer_email,
                    c.name AS customer_name,
                    c.company AS customer_company
                FROM tickets t
                JOIN customers c ON c.id = t.customer_id
                ORDER BY t.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_by_id(self, ticket_id: int) -> dict[str, Any] | None:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    c.email AS customer_email,
                    c.name AS customer_name,
                    c.company AS customer_company
                FROM tickets t
                JOIN customers c ON c.id = t.customer_id
                WHERE t.id = ?
                """,
                (ticket_id,),
            ).fetchone()
            return row_to_dict(row)

    def set_status(self, ticket_id: int, status: str) -> dict[str, Any] | None:
        with connect() as conn:
            conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            return row_to_dict(row)

    def set_lifecycle_stage(
        self, ticket_id: int, lifecycle_stage: str
    ) -> dict[str, Any] | None:
        with connect() as conn:
            conn.execute(
                "UPDATE tickets SET lifecycle_stage = ? WHERE id = ?",
                (lifecycle_stage, ticket_id),
            )
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            return row_to_dict(row)

    _SETTLEMENT_FIELDS = (
        "coverage_decision",
        "decision_note",
        "repair_authorized",
        "payment_arranged",
    )

    def update_settlement(
        self, ticket_id: int, **fields: Any
    ) -> dict[str, Any] | None:
        """Set one or more settlement fields (coverage_decision, decision_note,
        repair_authorized, payment_arranged)."""
        updates: list[str] = []
        values: list[Any] = []
        for name, value in fields.items():
            if name not in self._SETTLEMENT_FIELDS:
                raise ValueError(f"unknown settlement field: {name}")
            updates.append(f"{name} = ?")
            values.append(int(value) if name in ("repair_authorized", "payment_arranged") else value)
        if not updates:
            return self.get_by_id(ticket_id)
        with connect() as conn:
            values.append(ticket_id)
            conn.execute(
                f"UPDATE tickets SET {', '.join(updates)} WHERE id = ?", values
            )
        return self.get_by_id(ticket_id)

    def close(
        self, ticket_id: int, outcome: str
    ) -> dict[str, Any] | None:
        with connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET outcome = ?, status = 'closed', lifecycle_stage = 'closed',
                    closed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (outcome, ticket_id),
            )
        return self.get_by_id(ticket_id)

    def count_open_for_customer(self, customer_email: str) -> int:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS open_count
                FROM tickets t
                JOIN customers c ON c.id = t.customer_id
                WHERE c.email = ? AND t.status = 'open'
                """,
                (customer_email,),
            ).fetchone()
            return int(row["open_count"]) if row else 0
