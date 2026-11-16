"""Logging setup, safe handling of bad knowledge files, and what gets (and doesn't get) logged."""

import logging
from datetime import datetime
from pathlib import Path

import pytest

import logging_config
from logging_config import LOG_FILE_NAME, reset_logging, setup_logging
from pawpal_system import Pet, Species, Task
from rag import Chunk, Retriever, load_chunks, retrieve_for_pet
from suggestions import suggest_from_guides


@pytest.fixture
def fresh_logging():
    """Start each test with no pawpal handlers, and clean up afterwards."""
    reset_logging()
    yield
    reset_logging()


def handlers():
    return logging.getLogger("pawpal").handlers


# ---------- setup ----------

def test_setup_adds_console_and_file_handlers_and_writes_to_the_file(fresh_logging, tmp_path):
    logger = setup_logging(log_dir=tmp_path)
    assert len(handlers()) == 2
    logger.info("hello from the test")
    for h in handlers():
        h.flush()
    assert "hello from the test" in (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")


def test_setup_is_idempotent_so_streamlit_reruns_dont_duplicate_handlers(fresh_logging, tmp_path):
    setup_logging(log_dir=tmp_path)
    setup_logging(log_dir=tmp_path)
    setup_logging(log_dir=tmp_path)
    assert len(handlers()) == 2


def test_level_comes_from_the_argument_or_the_environment(fresh_logging, tmp_path, monkeypatch):
    assert setup_logging(level="debug", log_dir=tmp_path).level == logging.DEBUG
    reset_logging()
    monkeypatch.setenv("PAWPAL_LOG_LEVEL", "WARNING")
    assert setup_logging(log_dir=tmp_path).level == logging.WARNING


def test_unknown_level_falls_back_to_info_with_a_warning(fresh_logging, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="pawpal"):
        logger = setup_logging(level="LOUD", log_dir=tmp_path)
        level = logger.level  # read inside: caplog restores the old level on exit
    assert level == logging.INFO
    assert "Unknown PAWPAL_LOG_LEVEL" in caplog.text


def test_unwritable_log_folder_falls_back_to_console_only(fresh_logging, tmp_path, caplog):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("a file where a folder is needed")
    with caplog.at_level(logging.WARNING, logger="pawpal"):
        setup_logging(log_dir=blocker / "logs")  # must not raise
    assert len(handlers()) == 1  # console only
    assert "File logging disabled" in caplog.text


def test_log_folder_can_be_set_with_an_environment_variable(fresh_logging, tmp_path, monkeypatch):
    monkeypatch.setenv("PAWPAL_LOG_DIR", str(tmp_path / "custom"))
    setup_logging()
    assert (tmp_path / "custom" / LOG_FILE_NAME).exists()


def test_logs_folder_is_not_committed():
    ignore = (Path(logging_config.__file__).parent / ".gitignore").read_text(encoding="utf-8")
    assert "logs/" in ignore and "*.log" in ignore


# ---------- bad knowledge files are handled, not fatal ----------

GOOD = "---\ntitle: Good\nspecies: dog\nsource_url: https://example.org\n---\n\nBody.\n"


def test_missing_knowledge_folder_gives_an_empty_list_and_an_error_log(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="pawpal.rag"):
        assert load_chunks(tmp_path / "nope") == []
    assert "Knowledge directory not found" in caplog.text


def test_an_unreadable_guide_is_skipped_and_the_others_still_load(tmp_path, caplog):
    (tmp_path / "good.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "broken.md").write_bytes(b"\xff\xfe\x00 not valid utf-8 \x80\x81")
    with caplog.at_level(logging.WARNING, logger="pawpal.rag"):
        chunks = load_chunks(tmp_path)
    assert [c.id for c in chunks] == ["good"]
    assert "Skipping unreadable guide broken.md" in caplog.text


def test_an_empty_guide_is_skipped(tmp_path, caplog):
    (tmp_path / "good.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "empty.md").write_text("---\ntitle: Empty\n---\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="pawpal.rag"):
        chunks = load_chunks(tmp_path)
    assert [c.id for c in chunks] == ["good"]
    assert "Skipping empty guide empty.md" in caplog.text


def test_guides_with_missing_or_odd_metadata_still_load_but_warn(tmp_path, caplog):
    (tmp_path / "odd.md").write_text("---\nspecies: dogs\n---\n\nBody text.\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="pawpal.rag"):
        (chunk,) = load_chunks(tmp_path)
    assert chunk.title == "Odd"
    for expected in ("has no title", "unknown species 'dogs'", "no source_url"):
        assert expected in caplog.text


def test_loading_no_guides_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="pawpal.rag"):
        assert load_chunks(tmp_path) == []
    assert "No guides loaded" in caplog.text


def test_an_empty_knowledge_base_gives_no_suggestions_and_does_not_crash(caplog):
    pet = Pet("Rex", 3, "Beagle", Species.DOG)
    with caplog.at_level(logging.WARNING, logger="pawpal"):
        assert retrieve_for_pet(pet, retriever=Retriever([])) == []
        assert suggest_from_guides(pet, retriever=Retriever([])) == []
    assert "knowledge base is empty" in caplog.text


# ---------- what the pipeline logs ----------

def test_retrieval_and_suggestions_log_their_results(caplog):
    pet = Pet("Rex", 3, "Beagle", Species.DOG)
    with caplog.at_level(logging.INFO, logger="pawpal"):
        suggest_from_guides(pet)
    assert "Loaded 12 guide(s)" in caplog.text
    assert "Retrieved 6 guide(s) for species=dog life_stage=adult" in caplog.text
    assert "dog_feeding" in caplog.text
    assert "Suggested 10 task(s) for species=dog life_stage=adult from 6 guide(s)" in caplog.text


def test_debug_level_logs_queries_and_skipped_tasks(caplog):
    pet = Pet("Rex", 3, "Beagle", Species.DOG)
    pet.add_task(Task("Morning walk", datetime(2026, 1, 1, 8, 0), 30))
    with caplog.at_level(logging.DEBUG, logger="pawpal"):
        suggest_from_guides(pet)
    assert "query='feeding meals food water'" in caplog.text
    assert "Skipped 'Morning walk' from dog_exercise" in caplog.text


def test_an_unparseable_guide_line_is_logged_not_raised(caplog):
    bad = Chunk(id="bad", title="Bad", species="dog", source_urls=["https://example.org"],
                tags=["feeding"], text="feeding\n\n## Suggested tasks\n- no numbers here at all\n"
                                       "- Real task, 10 minutes, daily, high priority.\n")
    pet = Pet("Rex", 3, "Beagle", Species.DOG)
    with caplog.at_level(logging.WARNING, logger="pawpal"):
        result = suggest_from_guides(pet, retriever=Retriever([bad]))
    assert [s.description for s in result] == ["Real task"]
    assert "Unparseable suggested task in guide bad: 'no numbers here at all'" in caplog.text


def test_a_guide_without_a_task_list_is_logged(caplog):
    plain = Chunk(id="plain", title="Plain", species="dog", tags=["feeding"], text="feeding only prose")
    pet = Pet("Rex", 3, "Beagle", Species.DOG)
    with caplog.at_level(logging.WARNING, logger="pawpal"):
        assert suggest_from_guides(pet, retriever=Retriever([plain])) == []
    assert "Guide plain has no 'Suggested tasks' list" in caplog.text


def test_pet_and_task_names_never_appear_in_the_logs_even_at_debug(caplog):
    pet = Pet("Zorblax", 3, "Quokkaterrier", Species.DOG)
    pet.add_task(Task("Zorblax secret midnight ritual", datetime(2026, 1, 1, 8, 0), 30))
    with caplog.at_level(logging.DEBUG, logger="pawpal"):
        suggest_from_guides(pet)
    assert caplog.text  # something was logged
    for private in ("Zorblax", "Quokkaterrier", "secret midnight ritual"):
        assert private not in caplog.text
