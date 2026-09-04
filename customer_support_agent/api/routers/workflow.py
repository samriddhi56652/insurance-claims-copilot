"""Claim-workflow routes: the requirements checklist, the correspondence log,
and the follow-up / coverage-recommendation drafts."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from customer_support_agent.api.dependencies import (
    get_claim_correspondence_repository,
    get_claim_requirements_repository,
    get_copilot,
    get_copilot_or_503,
    get_customers_repository,
    get_draft_service,
    get_drafts_repository,
    get_tickets_repository,
    get_workflow_service,
)
from customer_support_agent.repositories.sqlite.claim_correspondence import (
    ClaimCorrespondenceRepository,
)
from customer_support_agent.repositories.sqlite.claim_requirements import (
    ClaimRequirementsRepository,
)
from customer_support_agent.repositories.sqlite.customers import CustomersRepository
from customer_support_agent.repositories.sqlite.drafts import DraftsRepository
from customer_support_agent.repositories.sqlite.tickets import TicketsRepository
from customer_support_agent.schemas.api import (
    ClaimWorkflowResponse,
    CorrespondenceCreateRequest,
    CorrespondenceResponse,
    GenerateDraftResponse,
    RequirementCreateRequest,
    RequirementResponse,
    RequirementUpdateRequest,
    SettlementUpdateRequest,
    TicketResponse,
)
from customer_support_agent.services.copilot_service import SupportCopilot
from customer_support_agent.services.draft_service import DraftService
from customer_support_agent.services.workflow_service import (
    STAGE_AWAITING,
    STAGE_CLOSED,
    STAGE_REVIEW_READY,
    STAGE_SETTLEMENT,
    WorkflowService,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_ticket(ticket_id: int, tickets_repo: TicketsRepository) -> dict[str, Any]:
    ticket = tickets_repo.get_by_id(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.get("/api/tickets/{ticket_id}/workflow", response_model=ClaimWorkflowResponse)
def get_workflow_route(
    ticket_id: int,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    workflow: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    _require_ticket(ticket_id, tickets_repo)
    return workflow.bundle(ticket_id)


@router.post(
    "/api/tickets/{ticket_id}/requirements", response_model=RequirementResponse
)
def add_requirement_route(
    ticket_id: int,
    payload: RequirementCreateRequest,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    requirements_repo: ClaimRequirementsRepository = Depends(
        get_claim_requirements_repository
    ),
    workflow: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    _require_ticket(ticket_id, tickets_repo)
    created = requirements_repo.add(
        ticket_id=ticket_id,
        item_label=payload.item_label,
        category=payload.category,
    )
    workflow.refresh_stage(ticket_id)
    return created


@router.patch(
    "/api/tickets/{ticket_id}/requirements/{req_id}",
    response_model=RequirementResponse,
)
def update_requirement_route(
    ticket_id: int,
    req_id: int,
    payload: RequirementUpdateRequest,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    requirements_repo: ClaimRequirementsRepository = Depends(
        get_claim_requirements_repository
    ),
    workflow: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    _require_ticket(ticket_id, tickets_repo)
    existing = requirements_repo.get_by_id(req_id)
    if not existing or existing.get("ticket_id") != ticket_id:
        raise HTTPException(status_code=404, detail="Requirement not found")

    updated = requirements_repo.update(
        req_id=req_id, status=payload.status, note=payload.note
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update requirement")
    workflow.refresh_stage(ticket_id)
    return updated


@router.post(
    "/api/tickets/{ticket_id}/correspondence", response_model=CorrespondenceResponse
)
def add_correspondence_route(
    ticket_id: int,
    payload: CorrespondenceCreateRequest,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    correspondence_repo: ClaimCorrespondenceRepository = Depends(
        get_claim_correspondence_repository
    ),
) -> dict[str, Any]:
    _require_ticket(ticket_id, tickets_repo)
    return correspondence_repo.add(
        ticket_id=ticket_id,
        direction=payload.direction,
        channel=payload.channel,
        body=payload.body,
    )


def _generate_lifecycle_draft(
    *,
    ticket_id: int,
    mode: str,
    required_stage: str,
    tickets_repo: TicketsRepository,
    customers_repo: CustomersRepository,
    drafts_repo: DraftsRepository,
    requirements_repo: ClaimRequirementsRepository,
    correspondence_repo: ClaimCorrespondenceRepository,
    draft_service: DraftService,
    copilot: SupportCopilot,
) -> dict[str, Any]:
    ticket = _require_ticket(ticket_id, tickets_repo)
    stage = ticket.get("lifecycle_stage") or "intake"
    if stage != required_stage:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Claim is at stage '{stage}'. This draft needs stage "
                f"'{required_stage}'."
            ),
        )

    customer = customers_repo.get_by_id(ticket["customer_id"])
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    requirements = requirements_repo.list_for_ticket(ticket_id)
    correspondence = correspondence_repo.list_for_ticket(ticket_id)

    try:
        draft = draft_service.generate_and_store(
            ticket_id=ticket_id,
            ticket=ticket,
            customer=customer,
            drafts_repo=drafts_repo,
            copilot=copilot,
            mode=mode,
            requirements=requirements,
            correspondence=correspondence,
        )
    except Exception as exc:  # noqa: BLE001 - mirror the manual-draft route
        detail = str(exc).lower()
        if "429" in detail or "rate limit" in detail or "rate_limit" in detail:
            raise HTTPException(
                status_code=503,
                detail="The AI service is rate-limited right now. Retry in a few seconds.",
            ) from exc
        logger.exception("Lifecycle draft (%s) failed for ticket_id=%s", mode, ticket_id)
        raise HTTPException(status_code=500, detail="Draft generation failed.") from exc

    return {"ticket_id": ticket_id, "draft": draft_service.serialize_draft(draft)}


@router.post(
    "/api/tickets/{ticket_id}/followup-draft", response_model=GenerateDraftResponse
)
def followup_draft_route(
    ticket_id: int,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    customers_repo: CustomersRepository = Depends(get_customers_repository),
    drafts_repo: DraftsRepository = Depends(get_drafts_repository),
    requirements_repo: ClaimRequirementsRepository = Depends(
        get_claim_requirements_repository
    ),
    correspondence_repo: ClaimCorrespondenceRepository = Depends(
        get_claim_correspondence_repository
    ),
    draft_service: DraftService = Depends(get_draft_service),
    copilot: SupportCopilot = Depends(get_copilot_or_503),
) -> dict[str, Any]:
    return _generate_lifecycle_draft(
        ticket_id=ticket_id,
        mode="followup_request",
        required_stage=STAGE_AWAITING,
        tickets_repo=tickets_repo,
        customers_repo=customers_repo,
        drafts_repo=drafts_repo,
        requirements_repo=requirements_repo,
        correspondence_repo=correspondence_repo,
        draft_service=draft_service,
        copilot=copilot,
    )


@router.post(
    "/api/tickets/{ticket_id}/coverage-recommendation",
    response_model=GenerateDraftResponse,
)
def coverage_recommendation_route(
    ticket_id: int,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    customers_repo: CustomersRepository = Depends(get_customers_repository),
    drafts_repo: DraftsRepository = Depends(get_drafts_repository),
    requirements_repo: ClaimRequirementsRepository = Depends(
        get_claim_requirements_repository
    ),
    correspondence_repo: ClaimCorrespondenceRepository = Depends(
        get_claim_correspondence_repository
    ),
    draft_service: DraftService = Depends(get_draft_service),
    copilot: SupportCopilot = Depends(get_copilot_or_503),
) -> dict[str, Any]:
    return _generate_lifecycle_draft(
        ticket_id=ticket_id,
        mode="coverage_recommendation",
        required_stage=STAGE_REVIEW_READY,
        tickets_repo=tickets_repo,
        customers_repo=customers_repo,
        drafts_repo=drafts_repo,
        requirements_repo=requirements_repo,
        correspondence_repo=correspondence_repo,
        draft_service=draft_service,
        copilot=copilot,
    )


# --- Settlement & closure ----------------------------------------------------


@router.patch(
    "/api/tickets/{ticket_id}/settlement", response_model=TicketResponse
)
def update_settlement_route(
    ticket_id: int,
    payload: SettlementUpdateRequest,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    requirements_repo: ClaimRequirementsRepository = Depends(
        get_claim_requirements_repository
    ),
    draft_service: DraftService = Depends(get_draft_service),
) -> dict[str, Any]:
    ticket = _require_ticket(ticket_id, tickets_repo)
    if (ticket.get("lifecycle_stage") or "") != STAGE_SETTLEMENT:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Claim is at stage '{ticket.get('lifecycle_stage')}'. Settlement "
                f"fields can only be set at stage '{STAGE_SETTLEMENT}'."
            ),
        )

    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No settlement fields provided.")
    updated = tickets_repo.update_settlement(ticket_id, **fields)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update settlement")
    return draft_service.serialize_ticket(
        updated, requirements_repo.counts_for_ticket(ticket_id)
    )


@router.post("/api/tickets/{ticket_id}/close", response_model=TicketResponse)
def close_claim_route(
    ticket_id: int,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    customers_repo: CustomersRepository = Depends(get_customers_repository),
    drafts_repo: DraftsRepository = Depends(get_drafts_repository),
    requirements_repo: ClaimRequirementsRepository = Depends(
        get_claim_requirements_repository
    ),
    draft_service: DraftService = Depends(get_draft_service),
    workflow: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    ticket = _require_ticket(ticket_id, tickets_repo)
    stage = ticket.get("lifecycle_stage") or ""
    if stage == STAGE_CLOSED:
        raise HTTPException(status_code=409, detail="Claim is already closed.")
    if stage != STAGE_SETTLEMENT:
        raise HTTPException(
            status_code=409,
            detail=f"Claim is at stage '{stage}'; it must be at '{STAGE_SETTLEMENT}' to close.",
        )
    if not workflow.can_close(ticket):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot close yet: record the coverage decision, and for an "
                "approval mark both the repair authorised and payment arranged "
                "(for a denial, add a reason note)."
            ),
        )

    closed = workflow.close_claim(ticket_id)
    if not closed:
        raise HTTPException(status_code=500, detail="Failed to close claim")

    # Write the customer-history memory from the real outcome. Best-effort -
    # closing the claim must succeed even if the memory backend is unavailable.
    try:
        customer = customers_repo.get_by_id(closed["customer_id"])
        cov = drafts_repo.latest_of_kind(ticket_id, "coverage_recommendation")
        draft_service_ctx = draft_service.parse_context_used(
            (cov or {}).get("context_used")
        )
        get_copilot().save_claim_closure(
            customer_email=customer["email"],
            customer_company=customer.get("company"),
            ticket=closed,
            coverage_rec_text=(cov or {}).get("content", ""),
            context_used=draft_service_ctx,
        )
    except Exception:
        logger.exception("Closure memory save failed for ticket_id=%s", ticket_id)

    return draft_service.serialize_ticket(
        closed, requirements_repo.counts_for_ticket(ticket_id)
    )


@router.post(
    "/api/tickets/{ticket_id}/closure-notice", response_model=GenerateDraftResponse
)
def closure_notice_route(
    ticket_id: int,
    tickets_repo: TicketsRepository = Depends(get_tickets_repository),
    customers_repo: CustomersRepository = Depends(get_customers_repository),
    drafts_repo: DraftsRepository = Depends(get_drafts_repository),
    requirements_repo: ClaimRequirementsRepository = Depends(
        get_claim_requirements_repository
    ),
    correspondence_repo: ClaimCorrespondenceRepository = Depends(
        get_claim_correspondence_repository
    ),
    draft_service: DraftService = Depends(get_draft_service),
    copilot: SupportCopilot = Depends(get_copilot_or_503),
) -> dict[str, Any]:
    ticket = _require_ticket(ticket_id, tickets_repo)
    stage = ticket.get("lifecycle_stage") or ""
    if stage not in (STAGE_SETTLEMENT, STAGE_CLOSED):
        raise HTTPException(
            status_code=409,
            detail=f"Claim is at stage '{stage}'; a closure notice needs settlement or closed.",
        )
    if not (ticket.get("coverage_decision") or "").strip():
        raise HTTPException(
            status_code=409, detail="Record the coverage decision first."
        )
    return _generate_lifecycle_draft(
        ticket_id=ticket_id,
        mode="closure_notice",
        required_stage=stage,
        tickets_repo=tickets_repo,
        customers_repo=customers_repo,
        drafts_repo=drafts_repo,
        requirements_repo=requirements_repo,
        correspondence_repo=correspondence_repo,
        draft_service=draft_service,
        copilot=copilot,
    )
