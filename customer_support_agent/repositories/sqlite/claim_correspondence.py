from __future__ import annotations

from typing import Any

from customer_support_agent.repositories.sqlite.base import connect, row_to_dict

DIRECTIONS = ("to_claimant", "from_claimant")
CHANNELS = ("email", "phone", "portal", "note")


class ClaimCorrespondenceRepository:
    """A plain log of what was sent to the claimant and what came back.

    There is no email integration - the adjuster records each exchange by hand.
    """

    def add(
        self,
        ticket_id: int,
        direction: str,
        body: str,
        channel: str = "email",
    ) -> dict[str, Any]:
        with connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO claim_correspondence (ticket_id, direction, channel, body)
                VALUES (?, ?, ?, ?)
                """,
                (ticket_id, direction, channel, body),
            )
            row = conn.execute(
                "SELECT * FROM claim_correspondence WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return row_to_dict(row) or {}

    def list_for_ticket(self, ticket_id: int) -> list[dict[str, Any]]:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM claim_correspondence
                WHERE ticket_id = ?
                ORDER BY created_at, id
                """,
                (ticket_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def latest_from_claimant(self, ticket_id: int) -> dict[str, Any] | None:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM claim_correspondence
                WHERE ticket_id = ? AND direction = 'from_claimant'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (ticket_id,),
            ).fetchone()
            return row_to_dict(row)
