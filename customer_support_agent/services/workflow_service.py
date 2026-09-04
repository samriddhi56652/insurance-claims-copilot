"""Claim lifecycle: seeding the checklist and moving the claim between stages.

Stages:
    intake              - registered; first (intake) draft pending / under review
    awaiting_documents  - intake reply sent; checklist active; chasing the claimant
    review_ready        - every checklist item verified or waived
    settlement          - a coverage recommendation was approved; the adjuster is
                          recording the coverage decision and the settlement steps
    closed              - terminal; outcome is approved / denied / withdrawn

`status` (open / closed) still drives the "open claim load" signal - a claim only
counts as closed once the whole lifecycle is done. `lifecycle_stage` is the
finer-grained position.
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
STAGE_SETTLEMENT = "settlement"
STAGE_CLOSED = "closed"

# refresh_stage only moves a claim between awaiting_documents and review_ready;
# every other stage is entered explicitly.
_REFRESH_TERMINAL = (STAGE_INTAKE, STAGE_SETTLEMENT, STAGE_CLOSED)


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
        if stage in _REFRESH_TERMINAL:
            return stage
        target = (
            STAGE_REVIEW_READY
            if self.requirements.all_satisfied(ticket_id)
            else STAGE_AWAITING
        )
        if target != stage:
            self.tickets.set_lifecycle_stage(ticket_id, target)
        return target

    def enter_settlement(self, ticket_id: int) -> None:
        """On coverage-recommendation approval: move into the settlement stage."""
        self.tickets.set_lifecycle_stage(ticket_id, STAGE_SETTLEMENT)

    def can_close(self, ticket: dict[str, Any]) -> bool:
        """A claim can close once the adjuster has recorded a decision and, for an
        approval, both settlement steps are done."""
        decision = (ticket.get("coverage_decision") or "").lower()
        if decision == "denied":
            return bool((ticket.get("decision_note") or "").strip())
        if decision == "approved":
            return bool(ticket.get("repair_authorized")) and bool(
                ticket.get("payment_arranged")
            )
        return False

    def close_claim(self, ticket_id: int) -> dict[str, Any] | None:
        """Set the terminal outcome from the recorded decision."""
        ticket = self.tickets.get_by_id(ticket_id)
        if not ticket:
            return None
        decision = (ticket.get("coverage_decision") or "").lower()
        outcome = "denied" if decision == "denied" else "approved"
        return self.tickets.close(ticket_id, outcome=outcome)

    def mark_resolved(self, ticket_id: int) -> None:  # kept for backward compatibility
        self.enter_settlement(ticket_id)

    def log_sent(self, ticket_id: int, body: str, channel: str = "email") -> None:
        """Record an approved draft as sent to the claimant."""
        self.correspondence.add(
            ticket_id=ticket_id,
            direction="to_claimant",
            body=body,
            channel=channel,
        )

    def bundle(self, ticket_id: int) -> dict[str, Any]:
        ticket = self.tickets.get_by_id(ticket_id) or {}
        stage = ticket.get("lifecycle_stage") or STAGE_INTAKE
        return {
            "ticket_id": ticket_id,
            "lifecycle_stage": stage,
            "requirement_counts": self.requirements.counts_for_ticket(ticket_id),
            "requirements": self.requirements.list_for_ticket(ticket_id),
            "correspondence": self.correspondence.list_for_ticket(ticket_id),
            "settlement": {
                "coverage_decision": ticket.get("coverage_decision"),
                "decision_note": ticket.get("decision_note"),
                "repair_authorized": bool(ticket.get("repair_authorized")),
                "payment_arranged": bool(ticket.get("payment_arranged")),
                "outcome": ticket.get("outcome"),
                "closed_at": ticket.get("closed_at"),
                "can_close": self.can_close(ticket),
            },
        }
