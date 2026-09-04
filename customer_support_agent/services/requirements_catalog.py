"""What the claimant must provide, by claim type.

Transcribed from knowledge_base/insurance-auto-required-documents-by-claim-type.md
and the FNOL intake checklist. Kept as a Python constant (not parsed from the
markdown at runtime) for the same reason the SLA snippet is a constant in
copilot_service.py: it is needed deterministically on every claim, so it is
given directly rather than left to retrieval.

Each entry is (item_label, category) where category is "information" (a fact the
claimant states) or "document" (a file they upload).
"""

from __future__ import annotations

# Facts every FNOL needs before an adjuster can place the loss. These match the
# fields requested in services/intake_check.INSUFFICIENT_INFO_REPLY.
_ALWAYS: tuple[tuple[str, str], ...] = (
    ("Date and time of the incident", "information"),
    ("Incident location (city, state, road/highway)", "information"),
    ("Description of what was damaged and how", "information"),
    ("Whether anyone was injured", "information"),
    ("Police report status and report number, if one was filed", "information"),
)

_BY_TYPE: dict[str, tuple[tuple[str, str], ...]] = {
    "Collision": (
        ("Driver's license copy", "document"),
        ("Vehicle registration copy", "document"),
        ("Scene photos - all sides and damage close-ups", "document"),
        ("Repair estimate from an approved shop", "document"),
        ("Police report, if one was filed", "document"),
    ),
    "Comprehensive": (
        ("Police/FIR complaint for theft or vandalism", "document"),
        ("Proof of ownership and key inventory (theft claims)", "document"),
        ("Photos/videos of the damage", "document"),
        ("Incident date/time declaration", "information"),
    ),
    "Theft": (
        ("Police/FIR complaint for the theft", "document"),
        ("Proof of ownership and full key inventory", "document"),
        ("Last-known-location and recovery details", "information"),
        ("Photos of where the vehicle was parked", "document"),
    ),
    "Glass Damage": (
        ("Damage photo showing the crack/chip spread", "document"),
        ("Vehicle details and policy number", "information"),
        ("Repair/replacement invoice (post-approval)", "document"),
    ),
    "Bodily Injury": (
        ("Medical reports and treatment summary", "document"),
        ("Hospital bills and discharge summary", "document"),
        ("Police / incident report", "document"),
        ("Contact details of the treating provider", "information"),
        ("Scene photos and repair estimate for the vehicle", "document"),
    ),
    "Property Damage": (
        ("Photos of the third party's damaged property", "document"),
        ("Third-party repair estimate or invoice", "document"),
        ("Police report, if one was filed", "document"),
        ("Claimant's account of how the damage occurred", "information"),
        ("Third-party contact and insurance details", "information"),
    ),
    "Other": (
        ("Photos of the damage", "document"),
        ("Repair estimate", "document"),
    ),
}


def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for label, category in items:
        key = label.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((label, category))
    return out


def requirements_for_claim(claim_type: str | None) -> list[tuple[str, str]]:
    """The checklist to seed for a claim of this type.

    Unknown / missing type falls back to the always-needed facts plus a generic
    photos + estimate pair.
    """
    key = (claim_type or "").strip()
    type_items = _BY_TYPE.get(key, _BY_TYPE["Other"])
    return _dedupe([*_ALWAYS, *type_items])


def known_claim_types() -> list[str]:
    return list(_BY_TYPE.keys())
