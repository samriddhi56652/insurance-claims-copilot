"""Tools the claims-copilot agent can call.

Design note: tools are for *precise, structured* lookups (an exact SLA, a
rule-based priority classification, a database count). Fuzzy "what does the
policy say about X" retrieval is RAG's job, not a tool's.

All three tools here return only real data:
  * get_claim_sla         - the fixed settlement SLA (mirrors the KB doc)
  * assess_claim_priority - rule check against the FNOL escalation triggers
  * lookup_open_ticket_load- a live count from the claims database

(The previous `lookup_customer_plan` fabricated a "plan tier" from a hash of
the email and is gone - see docs/DESIGN_GAPS.md and the eval findings.)
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import tool

from customer_support_agent.repositories.sqlite.customers import CustomersRepository
from customer_support_agent.repositories.sqlite.tickets import TicketsRepository


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


# --- Settlement SLA -----------------------------------------------------------
# Source of truth: knowledge_base/insurance-claims-settlement-sla-and-communication.md
# Kept here as a constant so the agent gets an exact, citeable answer rather
# than depending on that doc landing in the retrieved chunks.

_SLA_STAGES: list[dict[str, str]] = [
    {"stage": "FNOL acknowledgement", "target": "within 2 business hours"},
    {"stage": "First adjuster review touchpoint", "target": "within 1 business day"},
    {"stage": "Document sufficiency check", "target": "within 1 business day of receipt"},
    {"stage": "Preliminary coverage recommendation",
     "target": "within 2 business days after the required documents are received"},
]


@tool
def get_claim_sla(claim_type: str = "") -> str:
    """Return the internal claims-settlement SLA stages and their targets.

    These fixed service targets apply to every auto claim. Use them verbatim
    when telling a claimant what to expect - do not invent other timeframes.
    `claim_type` is optional and only adds an advisory note.
    """
    notes: list[str] = []
    ct = (claim_type or "").lower()
    if any(k in ct for k in ("injury", "bodily", "medical")):
        notes.append("Bodily-injury claims are additionally flagged for urgent adjuster review.")
    return _json(
        {
            "tool": "get_claim_sla",
            "claim_type": claim_type or None,
            "sla_stages": _SLA_STAGES,
            "notes": notes,
            "summary": "; ".join(f"{s['stage']}: {s['target']}" for s in _SLA_STAGES),
        }
    )


# --- Priority / escalation ---------------------------------------------------
# Source of truth: knowledge_base/insurance-auto-claims-fnol-intake-checklist.md
#   "Immediate Escalation Triggers" + "If bodily injury is reported, mark ... urgent"

_LARGE_LOSS_THRESHOLD = 25_000

_TRIGGER_PATTERNS: list[tuple[str, str]] = [
    ("hit_and_run", r"hit[\s-]?and[\s-]?run|fled the scene|left the scene|drove off after"),
    ("intoxication", r"\b(intoxicat\w*|drunk|dui|dwi|under the influence)\b"),
    ("multiple_injured_parties",
     r"\b(multiple|several|two|three|four|both) (people|passengers|parties|occupants|drivers)\b"
     r"[^.]{0,40}\b(injur\w*|hurt|hospital|ambulance)\b"),
    ("commercial_vehicle",
     r"\b(commercial vehicle|semi[\s-]?truck|tractor[\s-]?trailer|18[\s-]?wheeler|box truck|"
     r"delivery (truck|van)|fleet vehicle|company (van|truck|vehicle)|freight truck)\b"),
    ("conflicting_statements",
     r"\b(conflicting (account|statement)|disputes? fault|denies fault|"
     r"disagree\w* about (what|who|fault)|contradict\w* (statement|account))\b"),
]

_INJURY_STRONG = re.compile(
    r"\b(hospital|ambulance|paramedic|concussion|fracture|broken (bone|arm|leg|rib|collarbone)|"
    r"whiplash|emergency room|\bER\b|stitches|surgery|unconscious)\b",
    re.I,
)
_INJURY_WORD = re.compile(r"\b(injur(?:y|ies|ed)|hurt|bleeding|pain)\b", re.I)
_INJURY_NEGATED = re.compile(
    r"\bno (injur\w*|one (was |is )?(injur\w*|hurt))\b|\bwithout injur\w*\b|"
    r"\binjuries?:?\s*(none|no)\b|\bno bodily injury\b",
    re.I,
)


def _has_bodily_injury(text: str) -> bool:
    if _INJURY_STRONG.search(text):
        return True
    if _INJURY_WORD.search(text) and not _INJURY_NEGATED.search(text):
        return True
    return False


def _dollar_amounts(text: str) -> list[int]:
    out: list[int] = []
    for m in re.finditer(r"\$\s?([\d,]{2,})(?:\.\d+)?", text):
        try:
            out.append(int(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return out


@tool
def assess_claim_priority(description: str) -> str:
    """Classify a claim as 'urgent' or 'standard' against the FNOL escalation
    triggers: bodily injury, hit-and-run, intoxication, multiple injured
    parties, commercial-vehicle involvement, conflicting statements, or a
    large-loss estimate. Returns the matched triggers so the draft can be
    prioritised truthfully instead of guessed.
    """
    text = description or ""
    triggers: list[str] = []

    if _has_bodily_injury(text):
        triggers.append("bodily_injury")
    for name, pattern in _TRIGGER_PATTERNS:
        if re.search(pattern, text, re.I):
            triggers.append(name)
    if any(amt >= _LARGE_LOSS_THRESHOLD for amt in _dollar_amounts(text)):
        triggers.append(f"large_loss_estimate_over_{_LARGE_LOSS_THRESHOLD}")

    triggers = sorted(set(triggers))
    priority = "urgent" if triggers else "standard"
    reason = (
        "FNOL escalation trigger(s) present: " + ", ".join(triggers)
        if triggers
        else "No FNOL escalation triggers detected in the description."
    )
    return _json(
        {
            "tool": "assess_claim_priority",
            "priority": priority,
            "triggers": triggers,
            "reason": reason,
            "summary": f"Priority: {priority}. {reason}",
            "recommended_action": (
                "Route for urgent adjuster review."
                if priority == "urgent"
                else "Standard queue; proceed with normal SLA."
            ),
        }
    )


# --- Live database lookup ---------------------------------------------------

def _load_band(open_count: int) -> str:
    if open_count <= 1:
        return "light"
    if open_count <= 3:
        return "moderate"
    return "heavy"


@tool
def lookup_open_ticket_load(customer_email: str) -> str:
    """Return the open-claim count and load band for a customer email
    (queries the claims database)."""
    customers_repo = CustomersRepository()
    tickets_repo = TicketsRepository()

    customer = customers_repo.get_by_email(customer_email)
    if not customer:
        return _json(
            {
                "tool": "lookup_open_ticket_load",
                "customer_email": customer_email,
                "summary": f"No customer record found for {customer_email}.",
                "details": {"customer_found": False, "open_tickets": None, "load_band": "unknown"},
                "recommended_action": "Verify the customer email before promising an SLA.",
            }
        )

    open_count = tickets_repo.count_open_for_customer(customer_email)
    return _json(
        {
            "tool": "lookup_open_ticket_load",
            "customer_email": customer_email,
            "summary": f"Customer {customer_email} has {open_count} open claim(s).",
            "details": {
                "customer_found": True,
                "open_tickets": open_count,
                "load_band": _load_band(open_count),
            },
            "recommended_action": (
                "Acknowledge multiple ongoing claims." if open_count > 1 else "Handle as an isolated claim."
            ),
        }
    )


def get_support_tools() -> list:
    return [get_claim_sla, assess_claim_priority, lookup_open_ticket_load]
