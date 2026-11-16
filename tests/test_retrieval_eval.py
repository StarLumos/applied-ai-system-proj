"""Regression guard for retrieval quality. See eval_retrieval.py for the cases and the report."""

import pytest

from eval_retrieval import (
    K_QUERY,
    PROFILE_CASES,
    QUERY_CASES,
    ProfileResult,
    QueryCase,
    QueryResult,
    run_profile_cases,
    run_query_cases,
    summarize,
)
from rag import Retriever


@pytest.fixture(scope="module")
def retriever():
    return Retriever()


@pytest.fixture(scope="module")
def profiles(retriever):
    return run_profile_cases(retriever)


@pytest.fixture(scope="module")
def queries(retriever):
    return run_query_cases(retriever)


def test_eval_cases_only_reference_guides_that_exist(retriever):
    ids = {c.id for c in retriever.chunks}
    for case in PROFILE_CASES:
        assert set(case.expected) <= ids, case.name
    for case in QUERY_CASES:
        assert set(case.any_of) <= ids, case.question


@pytest.mark.parametrize("index", range(len(PROFILE_CASES)), ids=[c.name for c in PROFILE_CASES])
def test_profile_case(profiles, index):
    result = profiles[index]
    assert not result.missing, f"missing guides: {result.missing}"
    assert not result.wrong, f"wrong guides for this pet: {result.wrong}"


def test_every_query_finds_an_acceptable_guide_in_the_top_k(queries):
    misses = [r.case.question for r in queries if not r.hit_at_k]
    assert not misses, f"not in top {K_QUERY}: {misses}"


def test_aggregate_thresholds(profiles, queries):
    summary = summarize(profiles, queries)
    assert summary["profile_recall"] == 1.0
    assert summary["wrong_guides"] == 0
    assert summary["hit_at_1"] >= 0.90
    assert summary[f"hit_at_{K_QUERY}"] >= 0.95
    assert summary["mrr"] >= 0.90


def test_conversational_filler_does_not_outweigh_the_meaningful_word(retriever):
    """Regression: without stopwords for 'my/do/should', this ranked the toxic-foods guide
    below unrelated guides, because the filler words matched many documents."""
    hits = retriever.retrieve("my dog swallowed a raisin, what should I do", k=1)
    assert hits[0].chunk.id == "toxic_foods_and_hazards"


# ---------- the scoring itself ----------

def test_summarize_computes_the_metrics():
    case = PROFILE_CASES[0]
    profiles = [ProfileResult(case, ["a"], missing=[], wrong=[]),
                ProfileResult(case, ["a"], missing=[case.expected[0]], wrong=["x"])]
    queries = [QueryResult(QueryCase("q", ("a",)), ["a"], rank=1),
               QueryResult(QueryCase("q", ("a",)), ["b", "a"], rank=2),
               QueryResult(QueryCase("q", ("a",)), ["b", "c"], rank=None)]
    s = summarize(profiles, queries)
    n = len(case.expected)
    assert s["profile_cases_passed"] == 1 and s["wrong_guides"] == 1
    assert s["profile_recall"] == pytest.approx((2 * n - 1) / (2 * n))
    assert s["hit_at_1"] == pytest.approx(1 / 3)
    assert s[f"hit_at_{K_QUERY}"] == pytest.approx(2 / 3)
    assert s["mrr"] == pytest.approx((1 + 0.5 + 0) / 3)
