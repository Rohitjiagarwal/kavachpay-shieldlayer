"""Retrieval-quality eval for the secure RAG.

Seeds the Lumora knowledge base through the *real* ingestion pipeline, then runs
a labelled query set and reports recall@k and MRR@k over the hybrid retriever.
Optionally re-runs with Contextual Retrieval (Ollama) enabled and prints the
lift, so the enhancement is measured, not just claimed.

    python -m eval.rag_eval                 # baseline
    python -m eval.rag_eval --k 5 --contextual   # baseline vs contextual lift

Numbers depend on the embedder: FastEmbed (bge-small) if the `app` extra is
installed, else the deterministic hashing fallback. The active mode is printed,
so offline numbers are never mistaken for model numbers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from app import db
from app.rag import embed as emb
from app.rag import store as store_mod
from app.settings import SETTINGS

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "rag_golden.jsonl"
console = Console()


def _load_golden() -> list[dict]:
    return [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fresh_ingest() -> None:
    """Reset the vector store and re-ingest the KB under current settings."""
    store_mod._store = None  # drop the singleton so the run is clean
    from app.seed import ingest_kb  # imported late: pulls DB + scanner

    db.init_db()
    ingest_kb()


def _evaluate(golden: list[dict], k: int) -> dict:
    store = store_mod.get_store()
    recall_hits = 0
    rr_sum = 0.0
    per_query = []
    for g in golden:
        hits = store.search(g["query"], customer_id="public", top=k)
        doc_ids = [h.chunk.doc_id for h in hits]
        rank = next((i + 1 for i, d in enumerate(doc_ids) if d == g["doc_id"]), None)
        hit = rank is not None
        recall_hits += 1 if hit else 0
        rr_sum += (1.0 / rank) if rank else 0.0
        per_query.append((g["query"], g["doc_id"], rank))
    n = len(golden)
    return {
        "recall_at_k": recall_hits / n if n else 0.0,
        "mrr_at_k": rr_sum / n if n else 0.0,
        "n": n,
        "per_query": per_query,
    }


def _run(label: str, k: int, contextual: bool) -> dict:
    SETTINGS.enrich_context = contextual
    _fresh_ingest()
    res = _evaluate(_load_golden(), k)
    res["label"] = label
    res["contextual"] = contextual
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--contextual", action="store_true", help="also run with Ollama Contextual Retrieval and show lift")
    args = ap.parse_args()

    console.print(
        f"[bold]RAG retrieval eval[/bold]  embedder=[cyan]{emb.embedder_mode()}[/cyan] "
        f"store=[cyan]{store_mod.store_mode()}[/cyan]  k={args.k}"
    )

    runs = [_run("baseline", args.k, contextual=False)]
    if args.contextual:
        if not SETTINGS.ollama_model:
            console.print("[yellow]--contextual needs OLLAMA_MODEL set; skipping contextual run.[/yellow]")
        else:
            runs.append(_run(f"contextual ({SETTINGS.ollama_model})", args.k, contextual=True))

    t = Table(title="Retrieval quality")
    t.add_column("setup")
    t.add_column(f"recall@{args.k}", justify="right")
    t.add_column(f"MRR@{args.k}", justify="right")
    t.add_column("queries", justify="right")
    for r in runs:
        t.add_row(r["label"], f"{r['recall_at_k']:.3f}", f"{r['mrr_at_k']:.3f}", str(r["n"]))
    console.print(t)

    if len(runs) == 2:
        dr = runs[1]["recall_at_k"] - runs[0]["recall_at_k"]
        dm = runs[1]["mrr_at_k"] - runs[0]["mrr_at_k"]
        console.print(f"[bold]Contextual lift:[/bold] recall {dr:+.3f}, MRR {dm:+.3f}")

    # show any misses from the baseline for a quick error view
    misses = [(q, d) for (q, d, rank) in runs[0]["per_query"] if rank is None]
    if misses:
        console.print("\n[dim]baseline misses:[/dim]")
        for q, d in misses:
            console.print(f"  [red]MISS[/red] {d}: {q}")


if __name__ == "__main__":
    main()
