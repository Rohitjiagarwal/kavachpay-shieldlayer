"""Embeddings and reranking.

Real path (when the `app` extra is installed): FastEmbed
`BAAI/bge-small-en-v1.5` (dense) + `Qdrant/bm25` (sparse) +
`Xenova/ms-marco-MiniLM-L-6-v2` (reranker), all CPU, in-process.

Fallback path (bare laptop / CI): a deterministic hashing embedding and a
lexical reranker, so retrieval runs anywhere without model downloads. Which
path is active is reported by `embedder_mode()`.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache

DIM = 384

_fastembed_ok = None
_dense = None
_rerank = None


def _try_fastembed():
    global _fastembed_ok, _dense, _rerank
    if _fastembed_ok is not None:
        return _fastembed_ok
    if os.environ.get("DISABLE_FASTEMBED", "0") == "1":
        _fastembed_ok = False
        return False
    try:
        from fastembed import TextEmbedding  # type: ignore
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # type: ignore

        _dense = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        _rerank = TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2")
        _fastembed_ok = True
    except Exception:  # noqa: BLE001
        _fastembed_ok = False
    return _fastembed_ok


def embedder_mode() -> str:
    return "fastembed" if (_fastembed_ok or _try_fastembed()) else "fallback"


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _hash_embed(text: str) -> list[float]:
    """Deterministic bag-of-words hashing embedding, L2-normalised."""
    vec = [0.0] * DIM
    for tok in _tokens(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        idx = h % DIM
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: list[str]) -> list[list[float]]:
    if embedder_mode() == "fastembed":
        return [list(v) for v in _dense.embed(texts)]  # type: ignore
    return [_hash_embed(t) for t in texts]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def rerank(query: str, docs: list[str]) -> list[float]:
    """Return a relevance score per doc (higher = more relevant)."""
    if not docs:
        return []
    if embedder_mode() == "fastembed":
        return list(_rerank.rerank(query, docs))  # type: ignore
    # Fallback: lexical overlap (Jaccard-ish) scaled to ~0..1.
    q = set(_tokens(query))
    out = []
    for d in docs:
        dt = set(_tokens(d))
        if not q or not dt:
            out.append(0.0)
            continue
        inter = len(q & dt)
        out.append(inter / math.sqrt(len(q) * len(dt)))
    return out


@lru_cache(maxsize=1)
def bm25_tokenizer():
    return _tokens
