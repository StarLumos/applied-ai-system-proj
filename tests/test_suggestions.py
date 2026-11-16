import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from pawpal_system import Pet, Priority, Recurrence, Species, Task
from rag import Retriever, retrieve_for_pet
from suggestions import (
    MAX_SUGGESTIONS,
    NotConfiguredError,
    SuggestionError,
    build_user_prompt,
    generate_suggestions,
    parse_suggestions,
    suggest_for_pet,
)


def make_pet(age=3, species=Species.DOG, breed="Beagle"):
    return Pet(name="Rex", age=age, breed=breed, species=species)


def item(**overrides):
    base = {
        "description": "Morning walk",
        "duration_minutes": 30,
        "priority": "high",
        "recurrence": "daily",
        "source_id": "dog_exercise",
        "reason": "Dogs need daily exercise.",
    }
    base.update(overrides)
    return base


def reply(*items):
    return json.dumps({"suggestions": list(items)})


class StubClient:
    """Stands in for anthropic.Anthropic so tests never touch the network."""

    def __init__(self, text=None, stop_reason="end_turn", raises=None):
        self.calls = []
        self._text, self._stop, self._raises = text, stop_reason, raises
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        content = [SimpleNamespace(type="text", text=self._text)] if self._text is not None else []
        return SimpleNamespace(stop_reason=self._stop, content=content)


@pytest.fixture(scope="module")
def dog_hits():
    return retrieve_for_pet(make_pet())


# ---------- prompt ----------

def test_prompt_contains_profile_guides_and_existing_tasks(dog_hits):
    pet = make_pet(breed="Beagle")
    pet.add_task(Task("Evening walk", datetime(2026, 1, 1, 18, 0), 20))
    prompt = build_user_prompt(pet, dog_hits)
    assert "species: dog" in prompt and "breed: Beagle" in prompt and "life_stage: adult" in prompt
    assert "- Evening walk" in prompt
    assert '<guide id="dog_feeding"' in prompt and "source_url=" in prompt


def test_prompt_does_not_include_the_pet_name(dog_hits):
    assert "Rex" not in build_user_prompt(make_pet(), dog_hits)


def test_prompt_says_none_when_pet_has_no_tasks(dog_hits):
    assert "- (none)" in build_user_prompt(make_pet(), dog_hits)


# ---------- parsing / validation ----------

def test_valid_suggestion_is_converted_and_cited_from_the_guide(dog_hits):
    (s,) = parse_suggestions(reply(item()), dog_hits, [])
    assert (s.description, s.duration_minutes) == ("Morning walk", 30)
    assert s.priority is Priority.HIGH and s.recurrence is Recurrence.DAILY
    assert s.source_id == "dog_exercise"
    assert s.source_title == "Dog Exercise Needs"
    assert s.source_url.startswith("https://www.akc.org")  # resolved from the guide, not the model


def test_suggestion_citing_an_unretrieved_guide_is_dropped(dog_hits):
    assert parse_suggestions(reply(item(source_id="cat_feeding")), dog_hits, []) == []
    assert parse_suggestions(reply(item(source_id="made_up")), dog_hits, []) == []


@pytest.mark.parametrize("bad", [
    {"priority": "urgent"}, {"recurrence": "monthly"}, {"duration_minutes": 0},
    {"duration_minutes": 241}, {"duration_minutes": "30"}, {"duration_minutes": 30.5},
    {"duration_minutes": True}, {"description": ""}, {"description": "   "},
    {"description": "x" * 200}, {"description": None},
])
def test_invalid_entries_are_skipped_not_fatal(dog_hits, bad):
    good = item(description="Dinner feeding", source_id="dog_feeding")
    result = parse_suggestions(reply(item(**bad), good), dog_hits, [])
    assert [s.description for s in result] == ["Dinner feeding"]


def test_missing_field_skips_that_entry(dog_hits):
    broken = item()
    del broken["priority"]
    assert parse_suggestions(reply(broken), dog_hits, []) == []


def test_tasks_the_pet_already_has_and_repeats_are_skipped(dog_hits):
    result = parse_suggestions(
        reply(item(description="morning WALK"), item(description="Dinner feeding"),
              item(description="Dinner feeding")),
        dog_hits, ["Morning walk"])
    assert [s.description for s in result] == ["Dinner feeding"]


def test_results_are_capped(dog_hits):
    many = [item(description=f"Task {i}") for i in range(MAX_SUGGESTIONS + 5)]
    assert len(parse_suggestions(reply(*many), dog_hits, [])) == MAX_SUGGESTIONS


@pytest.mark.parametrize("raw", ["not json", "", "[]", "{}", '{"suggestions": "x"}', "null"])
def test_malformed_reply_raises_suggestion_error(dog_hits, raw):
    with pytest.raises(SuggestionError):
        parse_suggestions(raw, dog_hits, [])


def test_empty_list_is_valid(dog_hits):
    assert parse_suggestions(reply(), dog_hits, []) == []


# ---------- generation (stub client) ----------

def test_no_guides_means_no_api_call():
    client = StubClient(text=reply(item()))
    assert generate_suggestions(make_pet(), [], client=client) == []
    assert client.calls == []


def test_generate_sends_grounded_request_and_returns_suggestions(dog_hits):
    client = StubClient(text=reply(item()))
    result = generate_suggestions(make_pet(), dog_hits, client=client)
    assert [s.description for s in result] == ["Morning walk"]
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert "ONLY the care guides" in call["system"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in call  # not allowed on this model
    assert "<guide" in call["messages"][0]["content"]


def test_refusal_truncation_and_empty_reply_raise(dog_hits):
    with pytest.raises(SuggestionError):
        generate_suggestions(make_pet(), dog_hits, client=StubClient(text="", stop_reason="refusal"))
    with pytest.raises(SuggestionError):
        generate_suggestions(make_pet(), dog_hits, client=StubClient(text="{", stop_reason="max_tokens"))
    with pytest.raises(SuggestionError):
        generate_suggestions(make_pet(), dog_hits, client=StubClient(text=None))


def test_api_failure_becomes_suggestion_error(dog_hits):
    client = StubClient(raises=RuntimeError("boom"))
    with pytest.raises(SuggestionError):
        generate_suggestions(make_pet(), dog_hits, client=client)


def test_missing_credentials_raise_a_clear_error(dog_hits, monkeypatch):
    """The real SDK raises TypeError at request time when no credentials exist."""
    import anthropic

    def no_credentials(**kwargs):
        raise TypeError('"Could not resolve authentication method. Expected one of api_key, ..."')

    fake = SimpleNamespace(messages=SimpleNamespace(create=no_credentials))
    monkeypatch.setattr(anthropic, "Anthropic", lambda: fake)  # no network access possible
    with pytest.raises(NotConfiguredError, match="ANTHROPIC_API_KEY"):
        generate_suggestions(make_pet(), dog_hits)


def test_unrelated_type_errors_are_not_swallowed(dog_hits):
    def broken(**kwargs):
        raise TypeError("something else entirely")

    client = SimpleNamespace(messages=SimpleNamespace(create=broken))
    with pytest.raises(TypeError):
        generate_suggestions(make_pet(), dog_hits, client=client)


def test_suggest_for_pet_retrieves_then_generates():
    client = StubClient(text=reply(item(description="Brush teeth", source_id="dog_feeding")))
    result = suggest_for_pet(make_pet(), client=client, retriever=Retriever())
    assert [s.description for s in result] == ["Brush teeth"]
    assert '<guide id="dog_feeding"' in client.calls[0]["messages"][0]["content"]


# ---------- turning suggestions into tasks ----------

from datetime import date  # noqa: E402

from suggestions import Suggestion, default_start_times, suggestion_to_task  # noqa: E402


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
