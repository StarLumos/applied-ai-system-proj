"""Retrieval evaluation for PawPal+ RAG. Offline, deterministic, no API calls.

Two kinds of case, both scored against hand-written expectations:

* Profile cases: ``retrieve_for_pet`` on a pet profile. Each must return every guide the
  pet needs ("expected") and none that would be wrong for it ("forbidden", e.g. a
  cat guide for a dog or the puppy guide for a senior).
* Query cases: free-text questions through ``Retriever.retrieve``. Scored by whether
  an acceptable guide ("any_of") appears in the top 1 and top 3 results.

Run ``python eval_retrieval.py`` for a report; ``tests/test_retrieval_eval.py`` asserts on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from pawpal_system import Pet, Species
from rag import Retriever, retrieve_for_pet

K_QUERY = 3


@dataclass(frozen=True)
class ProfileCase:
    name: str
    species: Species
    age: int
    expected: tuple
    forbidden_prefixes: tuple = ()
    forbidden: tuple = ()


@dataclass(frozen=True)
class QueryCase:
    question: str
    any_of: tuple  # any one of these guides is an acceptable answer
    species: Optional[str] = None


COMMON = ("medication_administration", "toxic_foods_and_hazards")
DOG = ("dog_feeding", "dog_exercise", "dog_vaccinations_preventive_care", "dog_nail_care") + COMMON
CAT = ("cat_feeding", "cat_enrichment_play", "cat_litter_grooming",
       "cat_vaccinations_preventive_care") + COMMON

PROFILE_CASES: List[ProfileCase] = [
    ProfileCase("adult dog (3)", Species.DOG, 3, DOG, ("cat_",), ("puppy_care", "senior_pet_care")),
    ProfileCase("puppy (0)", Species.DOG, 0, DOG + ("puppy_care",), ("cat_",), ("senior_pet_care",)),
    ProfileCase("senior dog (10)", Species.DOG, 10, DOG + ("senior_pet_care",), ("cat_",), ("puppy_care",)),
    ProfileCase("adult cat (4)", Species.CAT, 4, CAT, ("dog_",), ("puppy_care", "senior_pet_care")),
    ProfileCase("kitten (0)", Species.CAT, 0, CAT, ("dog_",), ("puppy_care", "senior_pet_care")),
    ProfileCase("senior cat (12)", Species.CAT, 12, CAT + ("senior_pet_care",), ("dog_",), ("puppy_care",)),
    ProfileCase("unknown species, adult (3)", Species.ANY, 3, COMMON, (), ("puppy_care", "senior_pet_care")),
]

QUERY_CASES: List[QueryCase] = [
    QueryCase("can my dog eat chocolate or grapes", ("toxic_foods_and_hazards",)),
    QueryCase("are lilies poisonous to cats", ("toxic_foods_and_hazards",)),
    QueryCase("how often should I trim my dog's nails", ("dog_nail_care",)),
    QueryCase("how often should I scoop the litter box", ("cat_litter_grooming",)),
    QueryCase("how many meals a day should my kitten eat", ("cat_feeding",)),
    QueryCase("how many meals a day should my adult dog eat", ("dog_feeding",), "dog"),
    QueryCase("when do puppies get their first vaccines", ("puppy_care", "dog_vaccinations_preventive_care")),
    QueryCase("how do I give my dog a pill", ("medication_administration",)),
    QueryCase("can I give my dog ibuprofen", ("medication_administration", "toxic_foods_and_hazards")),
    QueryCase("how do I play with my cat", ("cat_enrichment_play",)),
    QueryCase("when is my cat considered a senior", ("senior_pet_care",)),
    QueryCase("how much exercise does my dog need", ("dog_exercise",)),
    QueryCase("what vaccines does my cat need", ("cat_vaccinations_preventive_care",), "cat"),
    QueryCase("how often should an older pet see the vet", ("senior_pet_care",)),
    # Harder: paraphrases that avoid the guides' own wording (a keyword retriever's weak spot).
    QueryCase("my dog swallowed a raisin, what should I do", ("toxic_foods_and_hazards",)),
    QueryCase("is it safe to give my cat tylenol", ("medication_administration", "toxic_foods_and_hazards")),
    QueryCase("when does my kitten need its shots", ("cat_vaccinations_preventive_care",)),
    QueryCase("how often does my aging pet need to see the doctor", ("senior_pet_care",)),
    QueryCase("my dog's claws are getting long", ("dog_nail_care",)),
]


@dataclass
class ProfileResult:
    case: ProfileCase
    returned: List[str]
    missing: List[str] = field(default_factory=list)
    wrong: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.wrong


@dataclass
class QueryResult:
    case: QueryCase
    returned: List[str]
    rank: Optional[int]  # 1-based rank of the first acceptable guide, None if absent from top K

    @property
    def hit_at_1(self) -> bool:
        return self.rank == 1

    @property
    def hit_at_k(self) -> bool:
        return self.rank is not None


def run_profile_cases(retriever: Retriever) -> List[ProfileResult]:
    results = []
    for case in PROFILE_CASES:
        pet = Pet(name="Test", age=case.age, breed="", species=case.species)
        returned = [h.chunk.id for h in retrieve_for_pet(pet, retriever=retriever)]
        results.append(ProfileResult(
            case,
            returned,
            missing=[g for g in case.expected if g not in returned],
            wrong=[g for g in returned
                   if g in case.forbidden or g.startswith(case.forbidden_prefixes)],
        ))
    return results


def run_query_cases(retriever: Retriever) -> List[QueryResult]:
    results = []
    for case in QUERY_CASES:
        returned = [h.chunk.id for h in retriever.retrieve(case.question, k=K_QUERY, species=case.species)]
        rank = next((i + 1 for i, g in enumerate(returned) if g in case.any_of), None)
        results.append(QueryResult(case, returned, rank))
    return results


def summarize(profiles: List[ProfileResult], queries: List[QueryResult]) -> dict:
    expected = sum(len(r.case.expected) for r in profiles)
    found = sum(len(r.case.expected) - len(r.missing) for r in profiles)
    n = len(queries)
    return {
        "profile_cases": len(profiles),
        "profile_cases_passed": sum(r.passed for r in profiles),
        "profile_recall": found / expected,
        "wrong_guides": sum(len(r.wrong) for r in profiles),
        "query_cases": n,
        "hit_at_1": sum(r.hit_at_1 for r in queries) / n,
        f"hit_at_{K_QUERY}": sum(r.hit_at_k for r in queries) / n,
        "mrr": sum(1 / r.rank for r in queries if r.rank) / n,
    }


def main() -> None:
    retriever = Retriever()
    profiles, queries = run_profile_cases(retriever), run_query_cases(retriever)

    print(f"Profile cases ({len(retriever.chunks)} guides in the knowledge base)")
    for r in profiles:
        print(f"  {'PASS' if r.passed else 'FAIL'}  {r.case.name}"
              + (f"  missing={r.missing}" if r.missing else "")
              + (f"  wrong={r.wrong}" if r.wrong else ""))
    print("\nQuery cases")
    for r in queries:
        mark = "top1" if r.hit_at_1 else ("top3" if r.hit_at_k else "MISS")
        print(f"  {mark:<4}  {r.case.question!r} -> {r.returned}")
    print("\nSummary")
    for key, value in summarize(profiles, queries).items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")


if __name__ == "__main__":
    main()
