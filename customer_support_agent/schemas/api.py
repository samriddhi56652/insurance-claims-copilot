from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, EmailStr, Field


class TicketCreateRequest(BaseModel):
    customer_email: EmailStr
    customer_name: str | None = None
    customer_company: str | None = None
    subject: str = Field(min_length=3)
    description: str = Field(min_length=10)
    claim_type: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    auto_generate: bool = True


class TicketResponse(BaseModel):
    id: int
    customer_id: int
    customer_email: EmailStr
    customer_name: str | None = None
    customer_company: str | None = None
    subject: str
    description: str
    claim_type: str | None = None
    status: str
    lifecycle_stage: str = "intake"
    priority: str
    coverage_decision: str | None = None
    outcome: str | None = None
    requirement_counts: dict[str, int] | None = None
    created_at: str
    updated_at: str


class DraftSignals(BaseModel):
    memory_hit_count: int = 0
    knowledge_hit_count: int = 0
    tool_call_count: int = 0
    tool_error_count: int = 0
    knowledge_sources: list[str] = Field(default_factory=list)


class DraftHighlights(BaseModel):
    memory: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class DraftToolCall(BaseModel):
    tool_name: str
    tool_call_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str
    summary: str | None = None
    output: dict[str, Any] | None = None
    output_text: str

class StructuredDraftContext(BaseModel):
    version: int = 2
    ticket: dict[str, Any] | None = None
    customer: dict[str, Any] | None = None
    signals: DraftSignals | dict[str, Any] | None = None
    highlights: DraftHighlights | dict[str, Any] | None = None
    memory_hits: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_hits: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[DraftToolCall | dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    # "intake_gate" when the claim was too thin to assess and the model never ran;
    # otherwise the agent runtime name.
    agent_runtime: str | None = None
    gated: str | None = None
    # Which lifecycle draft this is: intake_request / followup_request /
    # coverage_recommendation.
    draft_kind: str | None = None
    checklist_outstanding: list[str] = Field(default_factory=list)
    checklist_verified: list[str] = Field(default_factory=list)
    outcome: str | None = None

class DraftResponse(BaseModel):
    id: int
    ticket_id: int
    content: str
    context_used: StructuredDraftContext | dict[str, Any] | None = None
    kind: str = "intake_request"
    status: str
    created_at: str

class DraftUpdateRequest(BaseModel):
    content: str | None = None
    status: Literal["pending", "accepted", "discarded"] | None = None


class RequirementResponse(BaseModel):
    id: int
    ticket_id: int
    item_label: str
    category: str
    status: str
    note: str | None = None
    created_at: str
    updated_at: str


class RequirementCreateRequest(BaseModel):
    item_label: str = Field(min_length=2)
    category: Literal["document", "information"] = "document"


class RequirementUpdateRequest(BaseModel):
    status: Literal["needed", "received", "verified", "waived"] | None = None
    note: str | None = None


class CorrespondenceResponse(BaseModel):
    id: int
    ticket_id: int
    direction: str
    channel: str
    body: str
    created_at: str


class CorrespondenceCreateRequest(BaseModel):
    direction: Literal["to_claimant", "from_claimant"]
    channel: Literal["email", "phone", "portal", "note"] = "email"
    body: str = Field(min_length=1)


class SettlementState(BaseModel):
    coverage_decision: str | None = None
    decision_note: str | None = None
    repair_authorized: bool = False
    payment_arranged: bool = False
    outcome: str | None = None
    closed_at: str | None = None
    can_close: bool = False


class SettlementUpdateRequest(BaseModel):
    coverage_decision: Literal["approved", "denied"] | None = None
    decision_note: str | None = None
    repair_authorized: bool | None = None
    payment_arranged: bool | None = None


class ClaimWorkflowResponse(BaseModel):
    ticket_id: int
    lifecycle_stage: str
    requirement_counts: dict[str, int]
    requirements: list[RequirementResponse] = Field(default_factory=list)
    correspondence: list[CorrespondenceResponse] = Field(default_factory=list)
    settlement: SettlementState = Field(default_factory=SettlementState)

class GenerateDraftResponse(BaseModel):
    ticket_id: int
    draft: DraftResponse


class KnowledgeIngestRequest(BaseModel):
    clear_existing: bool = False

class KnowledgeIngestResponse(BaseModel):
    files_indexed: int
    chunks_indexed: int
    collection_count: int


class CustomerMemoriesResponse(BaseModel):
    customer_id: int
    customer_email: EmailStr
    memories: list[dict[str, Any]]



class CustomerMemorySearchResponse(BaseModel):
    customer_id: int
    customer_email: EmailStr
    query: str
    results: list[dict[str, Any]]