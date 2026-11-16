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
