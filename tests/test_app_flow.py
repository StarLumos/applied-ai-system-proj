"""End-to-end UI flows driven only through the page (nothing injected into session state).

Regression for a bug where st.selectbox returned a *copy* of the chosen Pet or Task, so
tasks added to the "selected" pet, and tasks marked complete, were lost on the copy: the
task tables stayed empty and "Generate schedule" said there was nothing to schedule.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def new_app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=30).run()


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click()
    return at.run()


def add_pet(at: AppTest, name: str) -> AppTest:
    next(t for t in at.text_input if t.label == "Pet name").set_value(name)
    return click(at, "Add pet")


def metrics(at: AppTest) -> dict:
    return {m.label: m.value for m in at.metric}


def test_suggested_task_appears_in_all_tasks_and_the_schedule():
    at = add_pet(new_app(), "Rex")
    at = click(at, "Suggest care tasks")
    at = click(at, "Add to schedule")
    assert not at.exception
    assert metrics(at) == {"Total tasks": "1", "Pending": "1", "Completed": "0"}

    at = click(at, "Generate schedule")
    assert any("Scheduled 1 task(s)" in s.value for s in at.success)
    assert not any("No pending tasks" in i.value for i in at.info)


def test_task_form_adds_to_the_first_pet_by_default():
    at = add_pet(add_pet(new_app(), "Rex"), "Luna")
    at = click(at, "Add task")
    assert not at.exception
    assert metrics(at)["Total tasks"] == "1"


def test_second_pet_can_be_chosen_for_a_new_task_and_the_pet_filter_works():
    at = add_pet(add_pet(new_app(), "Rex"), "Luna")
    form_pet = next(s for s in at.selectbox if s.label == "Pet" and s.key != "suggest_pet")
    luna_key = next(k for k in form_pet.options if "Luna" in k)
    form_pet.select(luna_key)
    at = click(at, "Add task")
    assert metrics(at)["Total tasks"] == "1"

    # The "All Tasks" pet filter is the third "Pet" selectbox on the page.
    filters = [s for s in at.selectbox if s.label == "Pet"]
    pet_filter = filters[-1]
    rex = next(k for k in pet_filter.options if "Rex" in k)
    pet_filter.select(rex)
    at.run()
    assert any("No tasks match these filters" in i.value for i in at.info)  # Rex has none

    pet_filter = [s for s in at.selectbox if s.label == "Pet"][-1]
    pet_filter.select(next(k for k in pet_filter.options if "Luna" in k))
    at.run()
    assert not any("No tasks match these filters" in i.value for i in at.info)


def test_marking_a_task_complete_updates_the_counts():
    at = add_pet(new_app(), "Rex")
    at = click(at, "Add task")
    assert metrics(at)["Pending"] == "1"
    at = click(at, "Mark complete")
    assert not at.exception
    at.run()  # the counts are drawn above the form, so they catch up on the next run
    assert metrics(at)["Completed"] == "1" and metrics(at)["Pending"] == "0"


# ---------- logging and safe error handling in the page ----------

import logging  # noqa: E402

import pytest  # noqa: E402

import suggestions  # noqa: E402


def test_user_actions_are_logged_without_private_details(caplog):
    with caplog.at_level(logging.INFO, logger="pawpal"):
        at = add_pet(new_app(), "Zorblax")
        at = click(at, "Suggest care tasks")
        at = click(at, "Add to schedule")
        at = click(at, "Generate schedule")
        at = click(at, "Mark complete")
    assert "Pet added: species=dog age=1 (now 1 pet(s))" in caplog.text
    assert "Suggested task added: source=dog_feeding priority=HIGH repeats=daily conflict=False" in caplog.text
    assert "Schedule generated: 1 scheduled, 0 outside available hours" in caplog.text
    assert "Task marked complete: repeats=daily next_created=True" in caplog.text
    assert "Zorblax" not in caplog.text and "Breakfast feeding" not in caplog.text


def test_a_blank_pet_name_is_rejected_and_logged(caplog):
    with caplog.at_level(logging.INFO, logger="pawpal"):
        at = click(new_app(), "Add pet")
    assert any("Pet name is required" in e.value for e in at.error)
    assert "Add pet rejected: name is required" in caplog.text


def test_a_failure_while_loading_suggestions_shows_a_friendly_error_and_logs_the_cause(monkeypatch, caplog):
    def boom(pet, **kwargs):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(suggestions, "suggest_from_guides", boom)
    at = add_pet(new_app(), "Rex")
    with caplog.at_level(logging.ERROR, logger="pawpal"):
        at = click(at, "Suggest care tasks")
    assert not at.exception  # the page did not crash
    assert any("Couldn't load care suggestions" in e.value for e in at.error)
    assert not any("disk exploded" in e.value for e in at.error)  # internals stay out of the UI
    assert "Failed to load care suggestions" in caplog.text
    assert "RuntimeError: disk exploded" in caplog.text  # ...but the traceback is in the log


def test_a_failure_while_adding_a_suggestion_is_contained(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise ValueError("bad task")

    at = add_pet(new_app(), "Rex")
    at = click(at, "Suggest care tasks")
    monkeypatch.setattr(suggestions, "suggestion_to_task", boom)
    with caplog.at_level(logging.ERROR, logger="pawpal"):
        at = click(at, "Add to schedule")
    assert not at.exception
    assert any("Couldn't add the suggested task" in e.value for e in at.error)
    assert "Failed to add the suggested task" in caplog.text
    assert not metrics(at)  # nothing was added: no task counts shown


def test_a_failure_while_generating_the_schedule_is_contained(monkeypatch, caplog):
    from pawpal_system import Scheduler

    def boom(self):
        raise RuntimeError("scheduler broke")

    monkeypatch.setattr(Scheduler, "build_schedule", boom)
    at = add_pet(new_app(), "Rex")
    with caplog.at_level(logging.ERROR, logger="pawpal"):
        at = click(at, "Generate schedule")
    assert not at.exception
    assert any("Couldn't generate the schedule" in e.value for e in at.error)
    assert "Failed to generate the schedule" in caplog.text
