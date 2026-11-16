"""Retrieval for PawPal+: loads the markdown knowledge base and ranks it with BM25.

No external dependencies and no LLM calls, so retrieval is deterministic and easy to test.
Each file in ``knowledge/`` becomes one :class:`Chunk`, so a citation is just the file's source.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have how if in into is it its of on or "
    "so that the their them then there these they this to was were what when which will with "
    "you your can may not no than also more most some such per".split()
)
_WORD = re.compile(r"[a-z0-9]+")

# Terms in `tags` and `title` are repeated so they outweigh passing mentions in the body.
_TITLE_WEIGHT = 3
_TAG_WEIGHT = 3


@dataclass
class Chunk:
    """One knowledge-base document plus the metadata needed for filtering and citing."""

    id: str
    title: str
    text: str
    species: str = "any"
    life_stage: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    source: str = ""
    source_urls: List[str] = field(default_factory=list)

    @property
    def source_url(self) -> str:
        return self.source_urls[0] if self.source_urls else ""


@dataclass
class Hit:
    chunk: Chunk
    score: float


def tokenize(text: str) -> List[str]:
    """Lowercase, split into words, drop stopwords, and fold simple plurals (walks -> walk)."""
    tokens = []
    for word in _WORD.findall(text.lower()):
        if word in _STOPWORDS:
            continue
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        tokens.append(word)
    return tokens


def _parse_frontmatter(raw: str) -> tuple[Dict[str, str], str]:
    """Split ``---`` delimited ``key: value`` frontmatter from the body."""
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    meta: Dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, parts[2].strip()


def _parse_list(value: str) -> List[str]:
    value = value.strip().strip("[]")
    return [item.strip() for item in value.split(",") if item.strip()]


def load_chunks(directory: Path = KNOWLEDGE_DIR) -> List[Chunk]:
    """Load every ``*.md`` file in ``directory`` (except the README) as a Chunk."""
    chunks = []
    for path in sorted(Path(directory).glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        urls = [
            meta[key]
            for key in sorted(k for k in meta if k.startswith("source_url"))
            if meta[key]
        ]
        chunks.append(
            Chunk(
                id=path.stem,
                title=meta.get("title", path.stem.replace("_", " ").title()),
                text=body,
                species=meta.get("species", "any").lower(),
                life_stage=meta.get("life_stage", "").lower() or None,
                tags=_parse_list(meta.get("tags", "")),
                source=meta.get("source", ""),
                source_urls=urls,
            )
        )
    return chunks


class BM25:
    """Okapi BM25 over a fixed list of token lists."""

    def __init__(self, docs: List[List[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avg_len = (sum(self.lengths) / len(docs)) if docs else 0.0
        df: Counter = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query_tokens: List[str], index: int) -> float:
        doc, length = self.docs[index], self.lengths[index]
        total = 0.0
        for term in set(query_tokens):
            freq = doc.get(term, 0)
            if not freq:
                continue
            norm = freq + self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1))
            total += self.idf[term] * freq * (self.k1 + 1) / norm
        return total


class Retriever:
    """Ranks knowledge chunks for a query, optionally restricted to a pet's profile."""

    def __init__(self, chunks: Optional[List[Chunk]] = None) -> None:
        self.chunks = load_chunks() if chunks is None else list(chunks)
        self._bm25 = BM25([self._doc_tokens(c) for c in self.chunks])

    @staticmethod
    def _doc_tokens(chunk: Chunk) -> List[str]:
        return (
            tokenize(chunk.title) * _TITLE_WEIGHT
            + tokenize(" ".join(chunk.tags)) * _TAG_WEIGHT
            + tokenize(chunk.text)
        )

    @staticmethod
    def _eligible(
        chunk: Chunk,
        species: Optional[str],
        life_stage: Optional[str],
    ) -> bool:
        if species and chunk.species not in ("any", species.lower()):
            return False
        if life_stage and chunk.life_stage and chunk.life_stage != life_stage.lower():
            return False
        return True

    def retrieve(
        self,
        query: str,
        k: int = 3,
        species: Optional[str] = None,
        life_stage: Optional[str] = None,
    ) -> List[Hit]:
        """Return up to ``k`` chunks with a positive score, best first.

        ``species`` keeps that species plus species-neutral chunks. ``life_stage``
        only drops chunks written for a *different* stage; chunks with no stage
        stay eligible.
        """
        tokens = tokenize(query)
        if not tokens or k <= 0:
            return []
        hits = []
        for i, chunk in enumerate(self.chunks):
            if not self._eligible(chunk, species, life_stage):
                continue
            score = self._bm25.score(tokens, i)
            if score > 0:
                hits.append(Hit(chunk, score))
        hits.sort(key=lambda h: (-h.score, h.chunk.id))
        return hits[:k]
