from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from customer_support_agent.api.dependencies import (
    get_copilot,
    get_draft_service,
    get_drafts_repository,
    get_tickets_repository,
    get_workflow_service,
)
from customer_support_agent.repositories.sqlite.drafts import DraftsRepository
from customer_support_agent.repositories.sqlite.tickets import TicketsRepository
from customer_support_agent.schemas.api import DraftResponse, DraftUpdateRequest
from customer_support_agent.services.draft_service import DraftService
from customer_support_agent.services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/api/drafts/{ticket_id}", response_model=DraftResponse)
def get_draft_route(
    ticket_id: int,
    drafts_repo: DraftsRepository = Depends(get_drafts_repository),
    draft_service: DraftService = Depends(get_draft_service),
) -> dict:
    draft = drafts_repo.get_latest_for_ticket(ticket_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft_service.serialize_draft(draft)


@router.patch("/api/drafts/{draft_id}", response_model=DraftResponse)
def update_draft_route(
    draft_id: int,
    payload: DraftUpdateRequest,
    drafts_repo: DraftsRepository = Depends(get_drafts_repository),
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    draft_service: DraftService = Depends(get_draft_service),
    workflow: WorkflowService = Depends(get_workflow_service),
) -> dict:
    existing = drafts_repo.get_by_id(draft_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Draft not found")

    updated = drafts_repo.update(draft_id=draft_id, content=payload.content, status=payload.status)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update draft")

    if payload.status == "accepted":
        _handle_acceptance(
            draft_id=draft_id,
            draft_kind=existing.get("kind") or "intake_request",
            content=updated["content"],
            drafts_repo=drafts_repo,
            tickets_repo=tickets_repo,
            draft_service=draft_service,
            workflow=workflow,
        )

    return draft_service.serialize_draft(updated)


def _handle_acceptance(
    *,
    draft_id: int,
    draft_kind: str,
    content: str,
    drafts_repo: DraftsRepository,
    tickets_repo: TicketsRepository,
    draft_service: DraftService,
    workflow: WorkflowService,
) -> None:
    """Approving a draft means different things depending on which draft it is.

    - intake_request       -> record it as sent, seed the checklist, move the
                              claim to 'awaiting_documents'.
    - followup_request     -> record it as sent; the claim stays where it is.
    - coverage_recommendation -> resolve the claim and save the resolution memory
                              (this is the only draft that closes a claim).
    """
    relation = drafts_repo.get_ticket_and_customer_by_draft(draft_id)
    if not relation:
        return
    ticket_id = relation["ticket_id"]

    # Every approved claimant-facing draft is logged as sent. Best-effort.
    try:
        workflow.log_sent(ticket_id, content)
    except Exception:
        logger.exception("Failed to log sent correspondence for ticket_id=%s", ticket_id)

    if draft_kind == "coverage_recommendation":
        tickets_repo.set_status(ticket_id, "resolved")
        workflow.mark_resolved(ticket_id)
        try:
            context_used = draft_service.parse_context_used(relation.get("context_used"))
            get_copilot().save_accepted_resolution(
                customer_email=relation["customer_email"],
                customer_company=relation.get("customer_company"),
                ticket_subject=relation["subject"],
                ticket_description=relation["description"],
                draft_content=content,
                context_used=context_used,
            )
        except Exception:
            # Draft acceptance must still succeed even if the memory save fails.
            logger.exception("Resolution memory save failed for ticket_id=%s", ticket_id)
        return

    if draft_kind == "followup_request":
        workflow.refresh_stage(ticket_id)
        return

    # intake_request (default)
    ticket = tickets_repo.get_by_id(ticket_id)
    if ticket:
        workflow.seed_checklist_and_advance(ticket)
