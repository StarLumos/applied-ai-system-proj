"""UI tests for the "Suggest Care Tasks" section, using Streamlit's AppTest.

Suggestions come from the real guides, so the tests are deterministic. For an adult dog the
first suggestion is "Breakfast feeding" (10 min, high priority, daily), from dog_feeding.
"""

from datetime import datetime, time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import suggestions
from pawpal_system import Owner, Pet, Priority, Recurrence, Species, Task

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def make_app(species=Species.DOG, age=3):
    owner = Owner(name="Jordan")
    pet = Pet(name="Rex", age=age, breed="Beagle", species=species)
    owner.add_pet(pet)
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["owner"] = owner
    return at, owner, pet


def click(at, label):
    next(b for b in at.button if b.label == label).click()
    return at.run()


def texts(elements):
    return [e.value for e in elements]


@pytest.fixture
def added(monkeypatch):
    """Records every task attached to a pet. AppTest runs the script on a copy of the session
    state, so the Pet object made in the test is not the one the page mutates."""
    calls = []
    original = Pet.add_task

    def spy(self, task):
        calls.append(task)
        return original(self, task)

    monkeypatch.setattr(Pet, "add_task", spy)
    return calls


def test_page_loads_without_error_and_shows_the_section():
    at, _, _ = make_app()
    at.run()
    assert not at.exception
    assert any(h.value == "Suggest Care Tasks" for h in at.subheader)


def test_suggestions_are_listed_with_sources_and_nothing_is_added_yet(added):
    at, _, _ = make_app()
    at.run()
    at = click(at, "Suggest care tasks")
    assert not at.exception
    assert not at.warning and not at.error  # no notices: this mode has nothing to report
    assert any("Breakfast feeding" in m for m in texts(at.markdown))
    assert any("Morning walk" in m for m in texts(at.markdown))
    assert any("Dog Feeding Frequency" in c for c in texts(at.caption))
    assert added == []  # nothing is added until the user clicks Add


def test_suggestions_match_the_pets_species_and_life_stage():
    at, _, _ = make_app(species=Species.CAT, age=12)
    at.run()
    at = click(at, "Suggest care tasks")
    shown = " ".join(texts(at.markdown))
    assert "Scoop litter box" in shown and "Senior wellness exam" in shown
    assert "Morning walk" not in shown and "Kitten vaccination visit" not in shown


def test_add_button_adds_the_suggested_task(added):
    at, _, _ = make_app()
    at.run()
    at = click(at, "Suggest care tasks")
    at = click(at, "Add to schedule")
    assert not at.exception
    (task,) = added
    assert (task.description, task.duration) == ("Breakfast feeding", 10)
    assert task.priority is Priority.HIGH and task.recurrence is Recurrence.DAILY
    assert task.start_time.hour == 8  # default start time
    assert any("Added 'Breakfast feeding'" in s.value for s in at.success)


def test_start_time_edit_is_used(added):
    at, _, _ = make_app()
    at.run()
    at = click(at, "Suggest care tasks")
    next(t for t in at.time_input if t.key and t.key.startswith("suggest_time_")).set_value(time(17, 15))
    at = click(at, "Add to schedule")
    assert (added[0].start_time.hour, added[0].start_time.minute) == (17, 15)


def test_added_suggestion_cannot_be_added_twice(added):
    at, _, _ = make_app()
    at.run()
    at = click(at, "Suggest care tasks")
    at = click(at, "Add to schedule")
    at.run()  # the next rerun replaces that card's button with an "Added" note
    assert len(added) == 1
    assert any("Added to the schedule" in s.value for s in at.success)


def test_adding_a_clashing_task_warns_but_still_adds(added):
    at, _, pet = make_app()
    pet.add_task(Task("Vet visit", datetime.combine(datetime.now().date(), time(8, 0)), 60))
    added.clear()
    at.run()
    at = click(at, "Suggest care tasks")
    at = click(at, "Add to schedule")  # first suggestion starts at 8:00, inside the vet visit
    assert len(added) == 1  # still added
    assert any("Heads up" in w.value and "Vet visit" in w.value for w in at.warning)


def test_empty_result_shows_a_friendly_message(monkeypatch):
    monkeypatch.setattr(suggestions, "suggest_from_guides", lambda pet, **kwargs: [])
    at, _, _ = make_app()
    at.run()
    at = click(at, "Suggest care tasks")
    assert not at.exception
    assert any("No new tasks to suggest" in i.value for i in at.info)


def test_species_any_shows_a_hint():
    at, _, _ = make_app(species=Species.ANY)
    at.run()
    assert any("species is 'Any'" in c.value for c in at.caption)


def test_no_pets_shows_a_prompt_instead_of_the_form():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Add a pet to get care suggestions" in i.value for i in at.info)
