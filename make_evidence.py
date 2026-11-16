"""Regenerate the saved execution evidence and refresh the README blocks that quote it.

    python make_evidence.py

1. Runs each command in COMMANDS with the current Python and saves its real output, with
   no hand editing, to docs/evidence/. Each file starts with a header: the command, the
   date, the Python version and the exit code. Your home folder and the project path are
   replaced with ``~`` and ``<project>`` so the files carry no personal paths.
2. Rewrites every ``<!-- evidence:NAME --> ... <!-- /evidence:NAME -->`` block in
   README.md from those files, so the numbers and outputs quoted there are the ones just
   produced.

Exits with status 1 if any command fails.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "docs" / "evidence"
README = ROOT / "README.md"
ORIGINAL_TEST_COUNT = 26  # tests that existed before the retrieval feature

# (output file, command arguments after the Python executable)
COMMANDS: List[Tuple[str, List[str]]] = [
    ("pytest_output.txt", ["-m", "pytest", "-v", "-p", "no:cacheprovider"]),
    ("eval_retrieval_output.txt", ["eval_retrieval.py"]),
    ("demo_interactions_output.txt", ["demo.py"]),
    ("demo_guardrails_output.txt", ["demo.py", "guardrails"]),
    ("scheduler_cli_output.txt", ["main.py"]),
]


# ---------------------------------------------------------------- running and saving

def sanitize(text: str) -> str:
    """Replace the project path and home folder so the saved files carry no personal paths."""
    for real, placeholder in ((str(ROOT), "<project>"), (str(Path.home()), "~")):
        for variant in (real, real.replace("\\", "/")):
            text = text.replace(variant, placeholder)
    return text


def run(args: List[str], log_dir: str) -> Tuple[int, str]:
    env = {**os.environ, "PAWPAL_LOG_DIR": log_dir, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    done = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return done.returncode, done.stdout


def generate() -> int:
    """Run every command and save its output. Returns the number of failed commands."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    failures = 0
    with tempfile.TemporaryDirectory() as log_dir:  # keep these runs out of the real logs/ folder
        for filename, args in COMMANDS:
            code, output = run(args, log_dir)
            command = "python " + " ".join(args)
            header = (f"$ {command}\n"
                      f"# generated {date.today().isoformat()} by make_evidence.py | "
                      f"Python {platform.python_version()} | exit code {code}\n\n")
            (EVIDENCE / filename).write_text(sanitize(header + output), encoding="utf-8")
            print(f"{'ok  ' if code == 0 else 'FAIL'} {command:<40} -> docs/evidence/{filename}")
            failures += code != 0
    return failures


# ---------------------------------------------------------------- README blocks

def read_body(name: str, evidence: Path = EVIDENCE) -> str:
    """An evidence file without its two header lines."""
    return (evidence / name).read_text(encoding="utf-8").split("\n\n", 1)[1].rstrip("\n")


def fence(text: str) -> str:
    return f"\n```text\n{text.rstrip(chr(10))}\n```\n"


def pytest_summary(evidence: Path) -> str:
    return read_body("pytest_output.txt", evidence).splitlines()[-1].strip("= ")


def count_passed(evidence: Path) -> int:
    match = re.match(r"(\d+) passed", pytest_summary(evidence))
    return int(match.group(1)) if match else 0


def block_pytest(evidence: Path) -> str:
    lines = (evidence / "pytest_output.txt").read_text(encoding="utf-8").rstrip("\n").splitlines()
    return fence("\n".join(lines[:8] + ["..."] + lines[-4:]))


def block_pytest_files(evidence: Path) -> str:
    text = (evidence / "pytest_output.txt").read_text(encoding="utf-8")
    # Parametrized test names can contain spaces, so match up to the final PASSED/FAILED word.
    passed = Counter(m.group(1) for m in re.finditer(r"^(tests/[^:\s]+)::.* PASSED\b", text, re.M))
    failed = Counter(m.group(1) for m in re.finditer(r"^(tests/[^:\s]+)::.* FAILED\b", text, re.M))
    expected = count_passed(evidence)
    if sum(passed.values()) != expected:
        raise ValueError(f"per-file counts add up to {sum(passed.values())} but pytest reported {expected}")
    rows = ["| Test file | Passed | Failed |", "|-----------|-------:|-------:|"]
    rows += [f"| `{name}` | {passed[name]} | {failed[name]} |" for name in sorted(passed.keys() | failed.keys())]
    return "\n" + "\n".join(rows) + "\n"


def block_eval(evidence: Path) -> str:
    lines = read_body("eval_retrieval_output.txt", evidence).splitlines()
    split = lines.index("Query cases")
    summary = lines.index("Summary")
    omitted = summary - split - 2
    return fence("\n".join(lines[:split] + [f"Query cases: {omitted} lines omitted here, see the full file", ""]
                           + lines[summary:]))


def block_reliability(evidence: Path) -> str:
    summary = dict(re.findall(r"^\s+(\w+): ([\d.]+)$", read_body("eval_retrieval_output.txt", evidence), re.M))
    guard = re.search(r"(\d+)/(\d+) guardrail checks passed",
                      read_body("demo_guardrails_output.txt", evidence))
    rows = [
        "| What was checked | Result | Full output |",
        "|------------------|--------|-------------|",
        f"| Automated tests | {pytest_summary(evidence)} | [pytest_output.txt](docs/evidence/pytest_output.txt) |",
        f"| Test pets get the right guides and no wrong ones | {summary['profile_cases_passed']} of "
        f"{summary['profile_cases']}, with {summary['wrong_guides']} wrong guides | "
        "[eval_retrieval_output.txt](docs/evidence/eval_retrieval_output.txt) |",
        f"| Questions find an acceptable guide | right guide first for "
        f"{round(float(summary['hit_at_1']) * 100)}%, in the top 3 for "
        f"{round(float(summary['hit_at_3']) * 100)}% of {summary['query_cases']} | "
        "[eval_retrieval_output.txt](docs/evidence/eval_retrieval_output.txt) |",
        f"| Guardrail checks | {guard.group(1)} of {guard.group(2)} passed | "
        "[demo_guardrails_output.txt](docs/evidence/demo_guardrails_output.txt) |",
    ]
    return "\n" + "\n".join(rows) + "\n"


def block_test_count(evidence: Path) -> str:
    total = count_passed(evidence)
    return f"{total} tests pass (the {ORIGINAL_TEST_COUNT} original plus {total - ORIGINAL_TEST_COUNT} new)"


BLOCKS: Dict[str, Callable[[Path], str]] = {
    "demo_interactions": lambda e: fence(read_body("demo_interactions_output.txt", e)),
    "reliability": block_reliability,
    "test_count": block_test_count,
    "pytest": block_pytest,
    "pytest_files": block_pytest_files,
    "eval": block_eval,
    "guardrails": lambda e: fence(read_body("demo_guardrails_output.txt", e)),
    "scheduler_cli": lambda e: fence(read_body("scheduler_cli_output.txt", e)),
}

MARKER = re.compile(r"(<!-- evidence:(\w+) -->)(.*?)(<!-- /evidence:\2 -->)", re.DOTALL)


def update_readme(readme: Path = README, evidence: Path = EVIDENCE) -> List[str]:
    """Rewrite each evidence block in the README from the saved files. Returns the block names."""
    text = readme.read_text(encoding="utf-8")
    updated: List[str] = []

    def replace(match: "re.Match[str]") -> str:
        name = match.group(2)
        if name not in BLOCKS:
            raise KeyError(f"README has an unknown evidence block: {name}")
        updated.append(name)
        return f"{match.group(1)}{BLOCKS[name](evidence)}{match.group(4)}"

    readme.write_text(MARKER.sub(replace, text), encoding="utf-8")
    return updated


def main() -> int:
    failures = generate()
    blocks = update_readme()
    print(f"README.md: refreshed {len(blocks)} evidence block(s): {', '.join(blocks)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
