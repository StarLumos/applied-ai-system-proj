"""Turning suggestions into scheduled tasks and picking their default start times."""

from datetime import date, datetime

from pawpal_system import Priority, Recurrence
from suggestions import Suggestion, default_start_times, suggestion_to_task


def make_suggestion(description="Morning walk", minutes=30, priority=Priority.HIGH,
                    recurrence=Recurrence.DAILY):
    return Suggestion(description, minutes, priority, recurrence, "why", "dog_exercise",
                      "Dog Exercise Needs", "https://example.org")


def test_suggestion_to_task_copies_fields_and_is_unattached():
    start = datetime(2026, 5, 1, 9, 30)
    task = suggestion_to_task(make_suggestion(), start)
    assert (task.description, task.duration, task.start_time) == ("Morning walk", 30, start)
    assert task.priority is Priority.HIGH and task.recurrence is Recurrence.DAILY
    assert task.pet is None and task.completed is False


def test_default_start_times_are_back_to_back_from_8am():
    day = date(2026, 5, 1)
    starts = default_start_times([make_suggestion(minutes=30), make_suggestion(minutes=45),
                                  make_suggestion(minutes=10)], day)
    assert starts == [datetime(2026, 5, 1, 8, 0), datetime(2026, 5, 1, 8, 30),
                      datetime(2026, 5, 1, 9, 15)]


def test_default_start_times_never_spill_past_the_day():
    day = date(2026, 5, 1)
    starts = default_start_times([make_suggestion(minutes=240)] * 6, day)
    assert all(s.date() == day for s in starts)
    assert starts[0] == datetime(2026, 5, 1, 8, 0)
    assert default_start_times([], day) == []
