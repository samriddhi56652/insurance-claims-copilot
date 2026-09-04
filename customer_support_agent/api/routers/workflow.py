"""Claim-workflow routes: the requirements checklist, the correspondence log,
and the follow-up / coverage-recommendation drafts."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from customer_support_agent.api.dependencies import (
    get_claim_correspondence_repository,
    get_claim_requirements_repository,
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
)
from customer_support_agent.services.copilot_service import SupportCopilot
from customer_support_agent.services.draft_service import DraftService
from customer_support_agent.services.workflow_service import (
    STAGE_AWAITING,
    STAGE_REVIEW_READY,
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
