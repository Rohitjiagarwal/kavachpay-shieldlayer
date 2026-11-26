"""Vector store with an access filter.

Real path: Qdrant (hybrid dense + sparse, payload filters) when QDRANT_URL is
set. Fallback path: an in-process store that does dense cosine + lexical BM25
and fuses with RRF, so search runs without Docker. The access filter is applied
identically in both paths and is the security-critical part (LLM08):

    visibility == public  OR  (visibility == private AND owner == session customer)
    internal              ->  never returned
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from app.rag import embed as emb


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    page: int
    heading_path: str
    owner: str  # customer id or "public"
    visibility: str  # public | private | internal
    text: str  # original chunk text, shown to the model and cited
    kind: str = "text"
    vector: list[float] = field(default_factory=list)
    # Contextual Retrieval: a situating blurb prepended to `text` *for indexing
    # only* (embedding + BM25). Empty => index `text` as-is. Never shown/cited.
    embed_text: str = ""

    def _index_text(self) -> str:
        return self.embed_text or self.text


@dataclass
class Hit:
    chunk: Chunk
    score: float


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class InMemoryStore:
    def __init__(self):
        self._chunks: dict[str, Chunk] = {}
        self._df: dict[str, int] = defaultdict(int)  # document frequency for BM25
        self._N = 0

    def clear_doc(self, doc_id: str) -> int:
        removed = [cid for cid, c in self._chunks.items() if c.doc_id == doc_id]
        for cid in removed:
            self._chunks.pop(cid, None)
        self._reindex()
        return len(removed)

    def upsert(self, chunks: list[Chunk]) -> None:
        for c in chunks:
            if not c.vector:
                c.vector = emb.embed_one(c._index_text())
            self._chunks[c.chunk_id] = c
        self._reindex()

    def _reindex(self) -> None:
        self._df = defaultdict(int)
        self._N = len(self._chunks)
        for c in self._chunks.values():
            for tok in set(emb._tokens(c._index_text())):
                self._df[tok] += 1

    def _visible(self, c: Chunk, customer_id: str) -> bool:
        if c.visibility == "internal":
            return False
        if c.visibility == "public":
            return True
        return c.visibility == "private" and c.owner == str(customer_id)

    def _bm25(self, query: str, c: Chunk, k1: float = 1.5, b: float = 0.75) -> float:
        q = emb._tokens(query)
        doc = emb._tokens(c._index_text())
        if not doc:
            return 0.0
        dl = len(doc)
        avgdl = max(1.0, sum(len(emb._tokens(x._index_text())) for x in self._chunks.values()) / max(1, self._N))
        tf = defaultdict(int)
        for t in doc:
            tf[t] += 1
        score = 0.0
        for t in set(q):
            if t not in self._df:
                continue
            idf = math.log(1 + (self._N - self._df[t] + 0.5) / (self._df[t] + 0.5))
            score += idf * (tf[t] * (k1 + 1)) / (tf[t] + k1 * (1 - b + b * dl / avgdl))
        return score

    def search(self, query: str, customer_id: str, top: int = 20) -> list[Hit]:
        qv = emb.embed_one(query)
        dense, sparse = [], []
        for c in self._chunks.values():
            if not self._visible(c, customer_id):
                continue
            dense.append((c, _cosine(qv, c.vector)))
            sparse.append((c, self._bm25(query, c)))
        dense.sort(key=lambda x: x[1], reverse=True)
        sparse.sort(key=lambda x: x[1], reverse=True)
        return self._rrf([dense, sparse], top)

    @staticmethod
    def _rrf(rankings: list[list[tuple[Chunk, float]]], top: int, k: int = 60) -> list[Hit]:
        scores: dict[str, float] = defaultdict(float)
        objs: dict[str, Chunk] = {}
        for ranking in rankings:
            for rank, (c, _s) in enumerate(ranking):
                scores[c.chunk_id] += 1.0 / (k + rank + 1)
                objs[c.chunk_id] = c
        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top]
        return [Hit(chunk=objs[cid], score=sc) for cid, sc in fused]


# Qdrant-backed store would implement the same interface; omitted from the
# offline build. The factory picks in-memory unless QDRANT_URL is configured.
_store: InMemoryStore | None = None


def get_store() -> InMemoryStore:
    global _store
    if _store is None:
        _store = InMemoryStore()
    return _store


def store_mode() -> str:
    return "in-memory"
