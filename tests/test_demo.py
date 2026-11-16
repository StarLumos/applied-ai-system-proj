"""The demo script and the evidence generator behind the README's execution evidence."""

from pathlib import Path

import pytest

import demo
import make_evidence

ROOT = Path(__file__).resolve().parent.parent


def test_interactions_demo_prints_every_example(capsys):
    assert demo.main([]) == 0
    out = capsys.readouterr().out
    for title in ("Example 1: an adult dog", "Example 2: a puppy", "Example 3: a senior cat",
                  "Example 4: searching the guides", "Example 5: a conflict is warned about"):
        assert title in out
    assert "10 suggestions, the first six shown" in out
    assert "Puppy meals" in out and "contains 'Senior wellness exam': False" in out
    assert "contains 'Kitten vaccination visit': False" in out
    assert "1. toxic_foods_and_hazards" in out
    assert "overlaps 'Vet check-up'" in out and "the task was still added" in out


def test_demo_output_is_deterministic(capsys):
    demo.main([])
    first = capsys.readouterr().out
    demo.main([])
    assert capsys.readouterr().out == first


def test_guardrail_checks_all_pass(capsys):
    assert demo.main(["guardrails"]) == 0
    out = capsys.readouterr().out
    assert f"{len(demo.CHECKS)}/{len(demo.CHECKS)} guardrail checks passed" in out
    assert "FAIL" not in out


def test_a_failing_or_crashing_check_is_reported_and_sets_a_failing_exit_code(monkeypatch, capsys):
    def crashes():
        raise RuntimeError("boom")

    monkeypatch.setattr(demo, "CHECKS", [("A bad check", lambda: (False, "nope")), ("A crash", crashes)])
    assert demo.main(["guardrails"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  A bad check: nope" in out
    assert "FAIL  A crash: raised RuntimeError: boom" in out
    assert "0/2 guardrail checks passed" in out


def test_guardrail_log_capture_restores_the_logger():
    import logging

    logger = logging.getLogger("pawpal")
    before = (logger.level, logger.propagate, list(logger.handlers))
    stream, restore = demo.capture_logs(logging.DEBUG)
    logger.warning("captured")
    restore()
    assert "captured" in stream.getvalue()
    assert (logger.level, logger.propagate, list(logger.handlers)) == before


def test_demo_rejects_an_unknown_mode():
    with pytest.raises(SystemExit):
        demo.main(["nonsense"])


# ---------- evidence generator ----------

def test_sanitize_replaces_the_project_path_and_home_folder():
    text = f"in {make_evidence.ROOT}\\tests and {str(make_evidence.ROOT).replace(chr(92), '/')}/x and {Path.home()}"
    cleaned = make_evidence.sanitize(text)
    assert "<project>" in cleaned and "~" in cleaned
    assert str(make_evidence.ROOT) not in cleaned and str(Path.home()) not in cleaned


def test_every_evidence_file_is_produced_by_a_listed_command_and_linked_from_the_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for filename, _ in make_evidence.COMMANDS:
        assert (ROOT / "docs" / "evidence" / filename).exists(), f"{filename} not generated"
        assert f"docs/evidence/{filename}" in readme, f"README doesn't link {filename}"


def test_saved_evidence_has_no_personal_paths_and_a_header():
    for filename, _ in make_evidence.COMMANDS:
        text = (ROOT / "docs" / "evidence" / filename).read_text(encoding="utf-8")
        assert text.startswith("$ python "), filename
        assert "exit code 0" in text.splitlines()[1], filename
        assert str(Path.home()) not in text and str(ROOT) not in text, filename


# ---------- README evidence blocks ----------

PYTEST_SAMPLE = """$ python -m pytest -v
# generated 2026-01-01 by make_evidence.py | Python 3.13 | exit code 0

============================= test session starts =============================
collected 4 items

tests/test_a.py::test_one PASSED [ 25%]
tests/test_a.py::test_param[a case with spaces (3)] PASSED [ 50%]
tests/test_b.py::test_two PASSED [ 75%]
tests/test_b.py::test_param[x y] PASSED [100%]

============================= 4 passed in 0.10s =============================
"""


def fake_evidence(tmp_path, pytest_text=PYTEST_SAMPLE):
    (tmp_path / "pytest_output.txt").write_text(pytest_text, encoding="utf-8")
    return tmp_path


def test_per_file_counts_include_tests_with_spaces_in_their_names(tmp_path):
    table = make_evidence.block_pytest_files(fake_evidence(tmp_path))
    assert "| `tests/test_a.py` | 2 | 0 |" in table
    assert "| `tests/test_b.py` | 2 | 0 |" in table


def test_per_file_counts_that_disagree_with_the_total_raise(tmp_path):
    broken = PYTEST_SAMPLE.replace("4 passed", "5 passed")
    with pytest.raises(ValueError, match="add up to 4 but pytest reported 5"):
        make_evidence.block_pytest_files(fake_evidence(tmp_path, broken))


def test_test_count_block_reports_new_tests_beyond_the_original(tmp_path):
    text = make_evidence.block_test_count(fake_evidence(tmp_path))
    assert text == f"4 tests pass (the {make_evidence.ORIGINAL_TEST_COUNT} original plus {4 - make_evidence.ORIGINAL_TEST_COUNT} new)"


def test_update_readme_rewrites_only_the_marked_blocks(tmp_path, monkeypatch):
    evidence = fake_evidence(tmp_path)
    monkeypatch.setitem(make_evidence.BLOCKS, "demo", lambda e: "\nNEW\n")
    readme = tmp_path / "README.md"
    readme.write_text("keep\n<!-- evidence:demo -->\nOLD\n<!-- /evidence:demo -->\nalso keep\n", encoding="utf-8")
    assert make_evidence.update_readme(readme, evidence) == ["demo"]
    assert readme.read_text(encoding="utf-8") == (
        "keep\n<!-- evidence:demo -->\nNEW\n<!-- /evidence:demo -->\nalso keep\n")


def test_update_readme_rejects_an_unknown_block(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("<!-- evidence:nope -->x<!-- /evidence:nope -->", encoding="utf-8")
    with pytest.raises(KeyError):
        make_evidence.update_readme(readme, tmp_path)


def test_every_block_in_the_readme_is_known_and_every_known_block_is_used():
    import re

    names = set(re.findall(r"<!-- evidence:(\w+) -->", (ROOT / "README.md").read_text(encoding="utf-8")))
    assert names == set(make_evidence.BLOCKS)
