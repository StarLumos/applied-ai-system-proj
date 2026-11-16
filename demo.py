"""Reproducible demo of PawPal+ care suggestions. No API key, network or browser needed.

    python demo.py               example inputs and the outputs they produce
    python demo.py guardrails    live checks of the filters and safety behavior

The output is deterministic: the same input always gives the same result.
The guardrails command exits with status 1 if any check fails.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import tempfile
from datetime import datetime, time
from pathlib import Path
from typing import Callable, List, Tuple

from pawpal_system import Owner, Pet, Priority, Scheduler, Species, Task
from rag import Retriever, life_stage_for, load_chunks, retrieve_for_pet
from suggestions import Suggestion, suggest_from_guides, suggestion_to_task


def line(s: Suggestion) -> str:
    return (f"  {s.description:<38} {s.duration_minutes:>3} min  {s.priority.name:<6}  "
            f"{s.recurrence.value:<6}  <- {s.source_title}")


def header(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------- example interactions

def interactions() -> None:
    adult = Pet("Buddy", 3, "Golden Retriever", Species.DOG)
    puppy = Pet("Pip", 0, "Labrador", Species.DOG)
    cat = Pet("Misty", 12, "Tabby", Species.CAT)

    header("Example 1: an adult dog")
    items = suggest_from_guides(adult)
    print(f"Input:  species=dog  age=3  breed='Golden Retriever'  existing tasks: none  "
          f"(life stage: {life_stage_for(adult)})")
    print(f"Output: {len(items)} suggestions, the first six shown")
    for s in items[:6]:
        print(line(s))

    header("Example 2: a puppy gets extra, stage-specific tasks")
    pup_items = suggest_from_guides(puppy)
    adult_names = {s.description for s in items}
    print(f"Input:  species=dog  age=0  breed='Labrador'  (life stage: {life_stage_for(puppy)})")
    print(f"Output: {len(pup_items)} suggestions: the adult dog's {len(adult_names)}, plus")
    for s in pup_items:
        if s.description not in adult_names:
            print(line(s))
    print("  contains 'Senior wellness exam':", any("Senior" in s.description for s in pup_items))

    header("Example 3: a senior cat")
    cat_items = suggest_from_guides(cat)
    print(f"Input:  species=cat  age=12  breed='Tabby'  (life stage: {life_stage_for(cat)})")
    print(f"Output: {len(cat_items)} suggestions, including")
    for s in cat_items:
        if s.description in ("Senior wellness exam", "Scoop litter box", "Flea preventive"):
            print(line(s))
    senior = next(s for s in cat_items if s.description == "Senior wellness exam")
    print(f"  source: {senior.source_url}")
    print("  contains 'Kitten vaccination visit':", any("Kitten" in s.description for s in cat_items))
    print("  contains any dog guide:", any(s.source_id.startswith("dog_") for s in cat_items))

    header("Example 4: searching the guides with a question")
    retriever = Retriever()
    for question in ("can my dog eat chocolate or grapes", "when does my kitten need its shots"):
        print(f'Input:  "{question}"')
        print("Output:")
        for rank, hit in enumerate(retriever.retrieve(question, k=3), 1):
            print(f"  {rank}. {hit.chunk.id:<34} score {hit.score:.2f}")
    print("  (the second question is a known weak spot: keyword search ranks the play guide above "
          "the vaccine guide, because the guide says 'vaccines', not 'shots')")

    header("Example 5: a conflict is warned about, not blocked")
    owner = Owner("Chelsea")
    buddy = Pet("Buddy", 3, "Golden Retriever", Species.DOG)
    owner.add_pet(buddy)
    day = datetime.now().date()
    buddy.add_task(Task("Vet check-up", datetime.combine(day, time(8, 0)), 60, Priority.HIGH))
    suggestion = suggest_from_guides(buddy)[0]
    task = suggestion_to_task(suggestion, datetime.combine(day, time(8, 15)))
    buddy.add_task(task)
    print("Input:  existing task 'Vet check-up' 08:00-09:00; add suggested "
          f"'{suggestion.description}' at 08:15")
    print("Output:", Scheduler(owner).check_conflict(task))
    print(f"        the task was still added: Buddy now has {len(buddy.list_tasks())} tasks")


# ---------------------------------------------------------------- guardrail checks

Check = Callable[[], Tuple[bool, str]]


def capture_logs(level: int = logging.DEBUG):
    """Attach an in-memory handler to the pawpal logger; returns (stream, restore)."""
    logger = logging.getLogger("pawpal")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    old_level, old_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    def restore() -> None:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate

    return stream, restore


def ids_for(species: Species, age: int) -> List[str]:
    return [h.chunk.id for h in retrieve_for_pet(Pet("x", age, "", species))]


def check_species_filter() -> Tuple[bool, str]:
    dog, cat = ids_for(Species.DOG, 3), ids_for(Species.CAT, 3)
    ok = not any(i.startswith("cat_") for i in dog) and not any(i.startswith("dog_") for i in cat)
    return ok, f"dog gets {len(dog)} guides, none cat; cat gets {len(cat)} guides, none dog"


def check_life_stage_filter() -> Tuple[bool, str]:
    puppy, senior, adult = ids_for(Species.DOG, 0), ids_for(Species.DOG, 10), ids_for(Species.DOG, 3)
    ok = ("puppy_care" in puppy and "senior_pet_care" not in puppy
          and "senior_pet_care" in senior and "puppy_care" not in senior
          and "puppy_care" not in adult and "senior_pet_care" not in adult)
    return ok, "puppy gets puppy_care only; senior gets senior_pet_care only; adult gets neither"


def check_stage_named_tasks() -> Tuple[bool, str]:
    names = [s.description for s in suggest_from_guides(Pet("x", 12, "", Species.CAT))]
    ok = "Kitten vaccination visit" not in names and "Senior wellness exam" in names
    return ok, "a 12-year-old cat is offered 'Senior wellness exam', not 'Kitten vaccination visit'"


def check_duplicates_skipped() -> Tuple[bool, str]:
    pet = Pet("x", 3, "", Species.DOG)
    pet.add_task(Task("morning WALK", datetime(2026, 1, 1, 8, 0), 30))
    names = [s.description.lower() for s in suggest_from_guides(pet)]
    ok = "morning walk" not in names and len(names) == len(set(names))
    return ok, "existing 'morning WALK' is not suggested again, and no suggestion repeats"


def check_limits_and_citations() -> Tuple[bool, str]:
    total = 0
    for species in (Species.DOG, Species.CAT, Species.ANY):
        for age in (0, 3, 12):
            for s in suggest_from_guides(Pet("x", age, "", species)):
                total += 1
                if not (1 <= s.duration_minutes <= 240 and len(s.description) <= 80
                        and s.source_url.startswith("https://") and s.source_title):
                    return False, f"bad suggestion: {s}"
    return True, f"{total} suggestions across 9 pet profiles: durations 1-240 min, each with an https source"


def check_citation_urls_intact() -> Tuple[bool, str]:
    chunks = {c.id: c for c in load_chunks()}
    ok = chunks["puppy_care"].source_url.endswith("part-i---veterinary-care") and all(
        c.source_url.startswith("https://") for c in chunks.values())
    return ok, f"all {len(chunks)} guides parse with a source URL (including one containing '---')"


def check_bad_knowledge_files() -> Tuple[bool, str]:
    good = "---\ntitle: Good\nspecies: dog\nsource_url: https://example.org\n---\n\nBody.\n"
    stream, restore = capture_logs(logging.WARNING)
    try:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "good.md").write_text(good, encoding="utf-8")
            (Path(folder) / "broken.md").write_bytes(b"\xff\xfe\x00 not valid utf-8 \x80")
            (Path(folder) / "empty.md").write_text("---\ntitle: Empty\n---\n", encoding="utf-8")
            chunks = load_chunks(Path(folder))
    finally:
        restore()
    logged = stream.getvalue()
    ok = [c.id for c in chunks] == ["good"] and "unreadable guide broken.md" in logged \
        and "empty guide empty.md" in logged
    return ok, "an unreadable and an empty guide are skipped and logged; the good one still loads"


def check_missing_knowledge_folder() -> Tuple[bool, str]:
    stream, restore = capture_logs(logging.ERROR)
    try:
        with tempfile.TemporaryDirectory() as folder:
            chunks = load_chunks(Path(folder) / "does_not_exist")
        suggestions = suggest_from_guides(Pet("x", 3, "", Species.DOG), retriever=Retriever(chunks))
    finally:
        restore()
    ok = chunks == [] and suggestions == [] and "Knowledge directory not found" in stream.getvalue()
    return ok, "a missing knowledge folder gives no suggestions and an error log, not a crash"


def check_conflict_warns_not_blocks() -> Tuple[bool, str]:
    owner, pet = Owner("x"), Pet("x", 3, "", Species.DOG)
    owner.add_pet(pet)
    day = datetime.now().date()
    pet.add_task(Task("Vet", datetime.combine(day, time(8, 0)), 60))
    new = Task("Walk", datetime.combine(day, time(8, 30)), 30)
    pet.add_task(new)
    warning = Scheduler(owner).check_conflict(new)
    return bool(warning) and new in pet.list_tasks(), "an overlapping task produces a warning and is still added"


def check_no_private_data_in_logs() -> Tuple[bool, str]:
    pet = Pet("Zorblax", 3, "Quokkaterrier", Species.DOG)
    pet.add_task(Task("Zorblax secret midnight ritual", datetime(2026, 1, 1, 8, 0), 30))
    stream, restore = capture_logs(logging.DEBUG)
    try:
        suggest_from_guides(pet)
    finally:
        restore()
    logged = stream.getvalue()
    leaked = [p for p in ("Zorblax", "Quokkaterrier", "secret midnight ritual") if p in logged]
    return bool(logged) and not leaked, \
        f"{len(logged.splitlines())} DEBUG log lines written; pet name, breed and task text absent"


CHECKS: List[Tuple[str, Check]] = [
    ("Species filter", check_species_filter),
    ("Life-stage filter", check_life_stage_filter),
    ("Wrong-stage tasks left out", check_stage_named_tasks),
    ("Duplicates skipped", check_duplicates_skipped),
    ("Limits and citations", check_limits_and_citations),
    ("Citation URLs intact", check_citation_urls_intact),
    ("Bad knowledge files handled", check_bad_knowledge_files),
    ("Missing knowledge folder handled", check_missing_knowledge_folder),
    ("Conflicts warn, never block", check_conflict_warns_not_blocks),
    ("No private data in logs", check_no_private_data_in_logs),
]


def guardrails() -> bool:
    print("PawPal+ guardrail checks (live)")
    passed = 0
    for name, check in CHECKS:
        try:
            ok, evidence = check()
        except Exception as exc:  # a crash is a failed check, not a crashed demo
            ok, evidence = False, f"raised {type(exc).__name__}: {exc}"
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {evidence}")
    print(f"\n{passed}/{len(CHECKS)} guardrail checks passed")
    print("App-level error containment and logging of user actions are covered by "
          "tests/test_app_flow.py and tests/test_logging.py (see the pytest output).")
    return passed == len(CHECKS)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("mode", nargs="?", choices=("interactions", "guardrails"), default="interactions")
    args = parser.parse_args(argv)
    if args.mode == "guardrails":
        return 0 if guardrails() else 1
    interactions()
    return 0


if __name__ == "__main__":
    sys.exit(main())
