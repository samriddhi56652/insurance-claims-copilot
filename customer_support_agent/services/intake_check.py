"""Pre-LLM intake gate.

The FNOL intake checklist requires the claim narrative to contain at least one
impact detail ("who/what was hit, lane/road condition, or point of impact").
The eval showed the model will not reliably withhold a coverage guess on thin
input - it asks for the missing facts *and* still names a coverage type. So a
claim that fails this rule never reaches the model: it gets a fixed request for
the missing FNOL fields instead. Deterministic on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Near-empty submissions ("help", "claim", "damage") are gated on length alone.
_MIN_COMBINED_CHARS = 25

# Impact-detail vocabulary, from
# knowledge_base/insurance-auto-claims-fnol-intake-checklist.md
# Each entry is matched at a word boundary (so "dent" does NOT fire on
# "acci-dent", and "collid" still catches "collision" / "collided").
_IMPACT_TERMS: tuple[str, ...] = (
    # collision verbs
    "hit", "struck", "collid", "rear-end", "rear end", "rearend", "sideswip",
    "backed into", "back into", "ran into", "run into", "t-bone", "t bone",
    "head-on", "head on", "crash", "smash", "slam", "pileup", "pile-up", "pile up",
    # point of impact / vehicle parts
    "bumper", "fender", "door", "hood", "trunk", "tailgate", "quarter panel",
    "windshield", "windscreen", "headlight", "tail light", "taillight",
    "mirror", "roof", "wheel", "tyre", "tire", "axle", "panel",
    # damage
    "dent", "scratch", "crack", "shatter", "totaled", "totalled", "write-off",
    "write off", "scrape", "gouge",
    # comprehensive perils
    "hail", "flood", "fire", "storm", "tree", "falling", "fell on", "theft",
    "stolen", "stole", "break-in", "broke into", "broken into", "vandal",
    "keyed", "graffiti", "arson",
    # loss of control / fixed objects
    "swerv", "skid", "spun", "spin out", "rolled", "roll over", "rollover",
    "flip", "slid", "hydroplane", "lost control", "off the road", "ditch",
    "guardrail", "guard rail", "pole", "curb", "kerb", "barrier",
)
_IMPACT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _IMPACT_TERMS) + r")", re.I
)


@dataclass
class IntakeResult:
    assessable: bool
    reasons: list[str] = field(default_factory=list)


def assess_intake(subject: str, description: str) -> IntakeResult:
    """True if the claim has enough to attempt a coverage assessment.

    Fails (gate closes) when the narrative names no impact detail, or when the
    whole submission is too short to be one.
    """
    combined = f"{subject or ''} {description or ''}".strip()
    reasons: list[str] = []

    if len(combined) < _MIN_COMBINED_CHARS:
        reasons.append("submission too short to contain incident details")
    if not _IMPACT_RE.search(combined):
        reasons.append(
            "narrative has no impact detail (what was hit / point of impact / "
            "road condition) as required by the FNOL intake rule"
        )
    return IntakeResult(assessable=not reasons, reasons=reasons)


# Sent when the gate closes. Built from the FNOL required-fields list + the SLA
# doc's pending-information messaging rules. No LLM involved.
INSUFFICIENT_INFO_REPLY = (
    "Thank you for contacting us about your recent incident - we have logged your "
    "claim.\n\n"
    "Before an adjuster can assess coverage, we need a few details that are missing "
    "from your report:\n\n"
    "1. Date and time of the incident\n"
    "2. Location (city, state, and road/highway if applicable)\n"
    "3. A brief description of what happened - specifically what was hit or damaged "
    'and how (for example, "another vehicle hit my rear bumper while I was stopped")\n'
    "4. Whether anyone was injured\n"
    "5. Police report status and report number, if one was filed\n\n"
    "Once we receive these, we will complete a document sufficiency check within "
    "1 business day and an adjuster will contact you. A coverage decision follows "
    "adjuster review."
)
