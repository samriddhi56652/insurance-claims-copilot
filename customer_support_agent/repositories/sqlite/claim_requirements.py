from __future__ import annotations

from typing import Any, Iterable

from customer_support_agent.repositories.sqlite.base import connect, row_to_dict

# status values a checklist item can hold
STATUSES = ("needed", "received", "verified", "waived")
# an item is "satisfied" (no longer blocking) when it is one of these
SATISFIED = ("verified", "waived")


class ClaimRequirementsRepository:
    """The per-claim documents / information checklist the adjuster works."""

    def bulk_create(
        self, ticket_id: int, items: Iterable[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        """Seed the checklist. `items` is (item_label, category) pairs.

        No-op if the claim already has requirements (so re-approving an intake
        draft does not duplicate the list).
        """
        with connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS n FROM claim_requirements WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()
            if existing and int(existing["n"]) > 0:
                return self.list_for_ticket(ticket_id)

            conn.executemany(
                """
                INSERT INTO claim_requirements (ticket_id, item_label, category)
                VALUES (?, ?, ?)
                """,
                [(ticket_id, label, category) for label, category in items],
            )
        return self.list_for_ticket(ticket_id)

    def add(
        self, ticket_id: int, item_label: str, category: str = "document"
    ) -> dict[str, Any]:
        with connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO claim_requirements (ticket_id, item_label, category)
                VALUES (?, ?, ?)
                """,
                (ticket_id, item_label, category),
            )
            row = conn.execute(
                "SELECT * FROM claim_requirements WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return row_to_dict(row) or {}

    def list_for_ticket(self, ticket_id: int) -> list[dict[str, Any]]:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM claim_requirements
                WHERE ticket_id = ?
                ORDER BY
                    CASE category WHEN 'information' THEN 0 ELSE 1 END,
                    id
                """,
                (ticket_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_by_id(self, req_id: int) -> dict[str, Any] | None:
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM claim_requirements WHERE id = ?", (req_id,)
            ).fetchone()
            return row_to_dict(row)

    def update(
        self,
        req_id: int,
        status: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        updates: list[str] = []
        values: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if note is not None:
            updates.append("note = ?")
            values.append(note)
        if not updates:
            return self.get_by_id(req_id)

        with connect() as conn:
            values.append(req_id)
            conn.execute(
                f"UPDATE claim_requirements SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            row = conn.execute(
                "SELECT * FROM claim_requirements WHERE id = ?", (req_id,)
            ).fetchone()
            return row_to_dict(row)

    def counts_for_ticket(self, ticket_id: int) -> dict[str, int]:
        rows = self.list_for_ticket(ticket_id)
        counts = {status: 0 for status in STATUSES}
        for row in rows:
            status = row.get("status") or "needed"
            counts[status] = counts.get(status, 0) + 1
        counts["total"] = len(rows)
        counts["outstanding"] = sum(
            1 for row in rows if (row.get("status") or "needed") not in SATISFIED
        )
        return counts

    def all_satisfied(self, ticket_id: int) -> bool:
        """True when the checklist exists and every item is verified or waived."""
        rows = self.list_for_ticket(ticket_id)
        if not rows:
            return False
        return all((row.get("status") or "needed") in SATISFIED for row in rows)
