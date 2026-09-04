"""Claim lifecycle: seeding the checklist and moving the claim between stages.

Stages:
    intake              - registered; first (intake) draft pending / under review
    awaiting_documents  - intake reply sent; checklist active; chasing the claimant
    review_ready        - every checklist item verified or waived
    resolved            - a coverage recommendation was approved

`status` (open / resolved) is left alone - it still drives the "open claim load"
signal. `lifecycle_stage` is the finer-grained position.
"""

from __future__ import annotations

from typing import Any

from customer_support_agent.repositories.sqlite.claim_correspondence import (
    ClaimCorrespondenceRepository,
)
from customer_support_agent.repositories.sqlite.claim_requirements import (
    ClaimRequirementsRepository,
)
from customer_support_agent.repositories.sqlite.tickets import TicketsRepository
from customer_support_agent.services.requirements_catalog import requirements_for_claim

STAGE_INTAKE = "intake"
STAGE_AWAITING = "awaiting_documents"
STAGE_REVIEW_READY = "review_ready"
STAGE_RESOLVED = "resolved"

_TERMINAL = (STAGE_INTAKE, STAGE_RESOLVED)


class WorkflowService:
    def __init__(
        self,
        tickets_repo: TicketsRepository | None = None,
        requirements_repo: ClaimRequirementsRepository | None = None,
        correspondence_repo: ClaimCorrespondenceRepository | None = None,
    ) -> None:
        self.tickets = tickets_repo or TicketsRepository()
        self.requirements = requirements_repo or ClaimRequirementsRepository()
        self.correspondence = correspondence_repo or ClaimCorrespondenceRepository()

    def seed_checklist_and_advance(self, ticket: dict[str, Any]) -> None:
        """On intake-draft approval: build the checklist, move to awaiting_documents."""
        items = requirements_for_claim(ticket.get("claim_type"))
        self.requirements.bulk_create(ticket["id"], items)
        if (ticket.get("lifecycle_stage") or STAGE_INTAKE) == STAGE_INTAKE:
            self.tickets.set_lifecycle_stage(ticket["id"], STAGE_AWAITING)

    def refresh_stage(self, ticket_id: int) -> str:
        """Recompute awaiting_documents <-> review_ready from the checklist state."""
        ticket = self.tickets.get_by_id(ticket_id)
        if not ticket:
            return STAGE_INTAKE
        stage = ticket.get("lifecycle_stage") or STAGE_INTAKE
        if stage in _TERMINAL:
            return stage
        target = (
            STAGE_REVIEW_READY
            if self.requirements.all_satisfied(ticket_id)
            else STAGE_AWAITING
        )
        if target != stage:
            self.tickets.set_lifecycle_stage(ticket_id, target)
        return target

    def mark_resolved(self, ticket_id: int) -> None:
        self.tickets.set_lifecycle_stage(ticket_id, STAGE_RESOLVED)

    def log_sent(self, ticket_id: int, body: str, channel: str = "email") -> None:
        """Record an approved draft as sent to the claimant."""
        self.correspondence.add(
            ticket_id=ticket_id,
            direction="to_claimant",
            body=body,
            channel=channel,
        )

    def bundle(self, ticket_id: int) -> dict[str, Any]:
        ticket = self.tickets.get_by_id(ticket_id)
        stage = (ticket or {}).get("lifecycle_stage") or STAGE_INTAKE
        return {
            "ticket_id": ticket_id,
            "lifecycle_stage": stage,
            "requirement_counts": self.requirements.counts_for_ticket(ticket_id),
            "requirements": self.requirements.list_for_ticket(ticket_id),
            "correspondence": self.correspondence.list_for_ticket(ticket_id),
        }
