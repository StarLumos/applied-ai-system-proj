"""Task suggestions for PawPal+, read from the retrieved care guides.

``rag.retrieve_for_pet`` picks the guides that fit a pet's species and life stage. Every
guide ends with a "## Suggested tasks" list such as

    - Morning walk, 30 minutes, daily, high priority.

``suggest_from_guides`` parses those lines into :class:`Suggestion` objects. Each one
carries its guide's title and URL as a citation. Nothing here calls a model or needs
credentials, so the output is deterministic. The task lists are curated defaults written
for this app, not statements made by the cited sources.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, List, Optional

from pawpal_system import Priority, Recurrence, Task
from rag import Retriever, life_stage_for, retrieve_for_pet

if TYPE_CHECKING:
    from pawpal_system import Pet

logger = logging.getLogger("pawpal.suggestions")

MAX_SUGGESTIONS = 20  # above what a pet's ~7 guides list in all (about 18 tasks)
MIN_DURATION, MAX_DURATION = 1, 240  # same bounds as the "Schedule a Task" form
MAX_DESCRIPTION_LEN = 80

_SECTION_HEADING = "## suggested tasks"
_DURATION = re.compile(r"(\d+)(?:\s*-\s*\d+)?\s*minutes?\b", re.IGNORECASE)
_PRIORITY = re.compile(r"\b(low|medium|high)\s+priority\b", re.IGNORECASE)
_REPEAT = re.compile(r"\b(daily|weekly)\b", re.IGNORECASE)


@dataclass
class Suggestion:
    description: str
    duration_minutes: int
    priority: Priority
    recurrence: Recurrence
    reason: str
    source_id: str
    source_title: str
    source_url: str


# ---------- turning suggestions into scheduled tasks ----------

def suggestion_to_task(suggestion: Suggestion, start_time: datetime) -> Task:
    """Build a (not yet attached) Task from a suggestion at the chosen start time."""
    return Task(
        description=suggestion.description,
        start_time=start_time,
        duration=suggestion.duration_minutes,
        priority=suggestion.priority,
        recurrence=suggestion.recurrence,
    )


def default_start_times(
    suggestions: List[Suggestion], day: date, first_hour: int = 8, last_hour: int = 21
) -> List[datetime]:
    """Back-to-back default start times on ``day`` so suggestions don't overlap each other.

    Starts at ``first_hour`` and runs on after each task. If the next start would be
    after ``last_hour`` it starts over at ``first_hour``, so times never spill past
    midnight; the user can edit any of them.
    """
    first = datetime.combine(day, time(first_hour))
    cursor = first
    starts = []
    for s in suggestions:
        if cursor.hour > last_hour or cursor.date() != day:
            cursor = first
        starts.append(cursor)
        cursor += timedelta(minutes=s.duration_minutes)
    return starts


# ---------- reading suggestions from the guides ----------

def _task_lines(text: str) -> List[str]:
    """Bullet lines in the guide's "Suggested tasks" section (empty if it has none)."""
    lines, inside = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## "):
            inside = stripped.lower() == _SECTION_HEADING
        elif inside and stripped.startswith("- "):
            lines.append(stripped[2:].strip().rstrip("."))
    return lines


def _parse_task_line(line: str, guide) -> Optional[Suggestion]:
    """Read "Description, N minutes, <how often>, <level> priority"; None if it isn't one.

    A lower bound is used for a range ("20-30 minutes" -> 20). Only "daily" and
    "weekly" become repeats; anything less frequent ("every 3-4 weeks", "monthly",
    "as prescribed") is left as a one-off task with the frequency kept in the reason.
    """
    parts = [p.strip() for p in line.split(",")]
    description = parts[0]
    duration = _DURATION.search(line)
    if not description or not duration:
        return None
    priority_match = _PRIORITY.search(line)
    priority = Priority[priority_match.group(1).upper()] if priority_match else Priority.MEDIUM

    frequency = ", ".join(
        p for p in parts[1:] if not _DURATION.search(p) and not _PRIORITY.search(p)
    )
    repeat = _REPEAT.search(frequency)
    recurrence = Recurrence(repeat.group(1).lower()) if repeat and not re.match(
        r"(every|monthly)", frequency, re.IGNORECASE) else Recurrence.NONE
    return Suggestion(
        description=description,
        duration_minutes=int(duration.group(1)),
        priority=priority,
        recurrence=recurrence,
        reason=(
            f"Suggested frequency: {frequency}."
            if frequency and frequency.lower() not in ("daily", "weekly")
            else "A standard task from this guide."
        ),
        source_id=guide.id,
        source_title=guide.title,
        source_url=guide.source_url,
    )


def _fits_stage(description: str, stage: Optional[str]) -> bool:
    """False for a task that names a life stage ("Kitten vaccination visit") the pet isn't in."""
    if stage is None:
        return True
    words = set(re.findall(r"[a-z]+", description.lower()))
    if words & {"puppy", "kitten"} and stage not in ("puppy", "kitten"):
        return False
    return not ("senior" in words and stage != "senior")


def suggest_from_guides(pet: "Pet", retriever: Optional[Retriever] = None) -> List[Suggestion]:
    """Suggestions read from the guides retrieved for ``pet``, each citing its guide.

    Skips tasks the pet already has, repeats, tasks aimed at a different life stage, and
    entries outside the description-length and duration limits.
    """
    taken = {t.description.strip().lower() for t in pet.list_tasks()}
    stage = life_stage_for(pet)
    hits = retrieve_for_pet(pet, retriever=retriever)
    out: List[Suggestion] = []
    for hit in hits:
        lines = _task_lines(hit.chunk.text)
        if not lines:
            logger.warning("Guide %s has no 'Suggested tasks' list; nothing to suggest from it",
                           hit.chunk.id)
        for line in lines:
            s = _parse_task_line(line, hit.chunk)
            if s is None:
                logger.warning("Unparseable suggested task in guide %s: %r", hit.chunk.id, line)
                continue
            reason = _skip_reason(s, taken, stage)
            if reason:
                logger.debug("Skipped %r from %s: %s", s.description, hit.chunk.id, reason)
                continue
            taken.add(s.description.lower())
            out.append(s)
            if len(out) == MAX_SUGGESTIONS:
                logger.warning("Suggestion limit (%d) reached; remaining tasks dropped", MAX_SUGGESTIONS)
                return out
    logger.info("Suggested %d task(s) for species=%s life_stage=%s from %d guide(s)",
                len(out), pet.species.value, stage, len(hits))
    return out


def _skip_reason(s: Suggestion, taken: set, stage: Optional[str]) -> Optional[str]:
    """Why a parsed suggestion should be left out, or None to keep it."""
    if not MIN_DURATION <= s.duration_minutes <= MAX_DURATION:
        return f"duration {s.duration_minutes} outside {MIN_DURATION}-{MAX_DURATION} minutes"
    if len(s.description) > MAX_DESCRIPTION_LEN:
        return "description too long"
    if s.description.lower() in taken:
        return "the pet already has it, or it was already suggested"
    if not _fits_stage(s.description, stage):
        return f"names a different life stage than {stage!r}"
    return None
