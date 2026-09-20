"""Knowledge-base search spreads across documents; claim types match loosely."""

from __future__ import annotations

from customer_support_agent.integrations.rag.chroma_kb import KnowledgeBaseService
from customer_support_agent.services.requirements_catalog import requirements_for_claim

diversify = KnowledgeBaseService._diversify_by_source


def hit(source: str, n: int) -> dict:
    return {"content": f"{source} chunk {n}", "source": source, "distance": n / 10}


def sources(hits: list[dict]) -> list[str]:
    return [h["source"] for h in hits]


def test_one_chunk_per_document_before_any_document_gets_a_second():
    # Nearest first: the top four are pairs from two files, the third file is 5th.
    candidates = [hit("a", 1), hit("a", 2), hit("b", 3), hit("b", 4), hit("c", 5), hit("c", 6)]
    picked = diversify(candidates, k=4)
    assert set(sources(picked)) == {"a", "b", "c"}
    assert len(picked) == 4


def test_fills_remaining_slots_by_nearness():
    candidates = [hit("a", 1), hit("a", 2), hit("a", 3), hit("b", 4)]
    picked = diversify(candidates, k=3)
    assert sources(picked) == ["a", "a", "b"]   # one 'b' forced in, then next-nearest 'a'


def test_keeps_similarity_order_in_the_result():
    candidates = [hit("a", 1), hit("b", 2), hit("c", 3), hit("d", 4)]
    picked = diversify(candidates, k=3)
    assert [h["distance"] for h in picked] == sorted(h["distance"] for h in picked)


def test_fewer_candidates_than_slots_returns_them_all():
    candidates = [hit("a", 1), hit("b", 2)]
    assert len(diversify(candidates, k=4)) == 2


def test_claim_type_lookup_ignores_case_and_knows_eval_aliases():
    canonical = requirements_for_claim("Property Damage")
    assert requirements_for_claim("property damage") == canonical
    assert requirements_for_claim("liability_property_damage") == canonical
    assert requirements_for_claim("comprehensive_theft") == requirements_for_claim("Comprehensive")


def test_unknown_claim_type_still_falls_back_to_other():
    assert requirements_for_claim("something-new") == requirements_for_claim("Other")
    assert requirements_for_claim(None) == requirements_for_claim("Other")
