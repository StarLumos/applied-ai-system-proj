"""Retrieval-only mode: suggestions read straight from the guides, no API key or model."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from pawpal_system import Pet, Priority, Recurrence, Species, Task
from rag import Retriever, load_chunks
from suggestions import _parse_task_line, _task_lines, suggest_from_guides

GUIDE = SimpleNamespace(id="g", title="A Guide", source_url="https://example.org")


def make_pet(age=3, species=Species.DOG, breed="Beagle"):
    return Pet(name="Rex", age=age, breed=breed, species=species)


@pytest.mark.parametrize("line, minutes, priority, recurrence", [
    ("Morning walk, 30 minutes, daily, high priority", 30, Priority.HIGH, Recurrence.DAILY),
    ("Evening walk, 20-30 minutes, daily, medium priority", 20, Priority.MEDIUM, Recurrence.DAILY),
    ("Rotate toys, 10 minutes, weekly, low priority", 10, Priority.LOW, Recurrence.WEEKLY),
    ("Brush coat, 10 minutes, weekly (daily for long-haired cats), low priority",
     10, Priority.LOW, Recurrence.WEEKLY),
    ("Puppy meals, 10 minutes each, three to four times daily, high priority",
     10, Priority.HIGH, Recurrence.DAILY),
    ("Nail trim, 15 minutes, every 3-4 weeks, low priority", 15, Priority.LOW, Recurrence.NONE),
    ("Weigh pet, 5 minutes, monthly, low priority", 5, Priority.LOW, Recurrence.NONE),
    ("Give medication, 5-10 minutes, as prescribed, high priority", 5, Priority.HIGH, Recurrence.NONE),
    ("Wellness exam, 60 minutes, high priority", 60, Priority.HIGH, Recurrence.NONE),
    ("Something, 15 minutes", 15, Priority.MEDIUM, Recurrence.NONE),
])
def test_parse_task_line(line, minutes, priority, recurrence):
    s = _parse_task_line(line, GUIDE)
    assert (s.duration_minutes, s.priority, s.recurrence) == (minutes, priority, recurrence)
    assert s.source_id == "g" and s.source_title == "A Guide"


def test_frequency_is_kept_in_the_reason_when_it_is_not_a_repeat():
    nail = _parse_task_line("Nail trim, 15 minutes, every 3-4 weeks, low priority", GUIDE)
    assert "every 3-4 weeks" in nail.reason
    walk = _parse_task_line("Walk, 30 minutes, daily, high priority", GUIDE)
    assert walk.reason == "A standard task from this guide."


@pytest.mark.parametrize("line", ["Just a note", "No duration here, high priority", ", 10 minutes"])
def test_unparseable_lines_return_none(line):
    assert _parse_task_line(line, GUIDE) is None


def test_task_lines_only_reads_the_suggested_tasks_section():
    text = (
        "# T\n\n- not a task, 1 minutes\n\n## Other\n- nor this, 5 minutes\n\n"
        "## Suggested tasks\nThese are defaults.\n"
        "- Real task, 10 minutes, daily, high priority.\n\n## After\n- ignored, 3 minutes\n"
    )
    assert _task_lines(text) == ["Real task, 10 minutes, daily, high priority"]
    assert _task_lines("no section at all") == []


def test_every_guide_has_parseable_suggested_tasks():
    for chunk in load_chunks():
        lines = _task_lines(chunk.text)
        assert lines, f"{chunk.id} has no suggested tasks"
        parsed = [_parse_task_line(line, chunk) for line in lines]
        assert all(parsed), f"{chunk.id}: unparseable line in {lines}"
        assert all(1 <= s.duration_minutes <= 240 for s in parsed), chunk.id


def test_guide_suggestions_match_the_pet_and_cite_their_guides():
    cat = suggest_from_guides(make_pet(age=4, species=Species.CAT, breed="Tabby"))
    allowed = {"medication_administration", "toxic_foods_and_hazards"}
    assert cat and all(s.source_id.startswith("cat_") or s.source_id in allowed for s in cat)
    assert all(s.source_url.startswith("https://") for s in cat)
    names = [s.description for s in cat]
    assert "Scoop litter box" in names
    assert len(names) == len(set(names))


def test_guide_suggestions_skip_tasks_the_pet_already_has():
    pet = make_pet()
    pet.add_task(Task("morning WALK", datetime(2026, 1, 1, 8, 0), 30))
    assert "Morning walk" not in [s.description for s in suggest_from_guides(pet)]


def names_for(age, species):
    return [s.description for s in suggest_from_guides(make_pet(age=age, species=species))]


def test_senior_cat_gets_senior_tasks_but_not_kitten_tasks():
    names = names_for(12, Species.CAT)
    assert "Senior wellness exam" in names and "Kitten vaccination visit" not in names
    assert "Vaccination booster appointment" in names  # still gets the non-stage-specific ones


def test_kitten_gets_kitten_tasks_but_not_senior_tasks():
    names = names_for(0, Species.CAT)
    assert "Kitten vaccination visit" in names and "Senior wellness exam" not in names


def test_adult_dog_gets_neither_puppy_nor_senior_tasks():
    names = names_for(3, Species.DOG)
    assert "Morning walk" in names
    assert not any("Puppy" in n or "Senior" in n for n in names)


def test_puppy_gets_puppy_tasks_including_the_vet_visit():
    names = names_for(0, Species.DOG)
    assert "Puppy meals" in names and "Vet vaccination visit" in names
    assert "Senior wellness exam" not in names


def test_no_matching_guides_gives_no_suggestions():
    assert suggest_from_guides(make_pet(), retriever=Retriever([])) == []


def test_retrieval_only_mode_never_creates_an_api_client(monkeypatch):
    import anthropic

    def boom(*args, **kwargs):
        raise AssertionError("the API client must not be created")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    assert suggest_from_guides(make_pet())
