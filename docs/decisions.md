# Decisions log

Every key architectural choice, one line each (newest first).

- **2026-11-26 — 3-Layer Zero-Judge Pipeline:** Replaced probabilistic neural classification and LLM-as-a-Judge scoring with a deterministic 3-stage funnel (`1A` Normalizer → `1B` Aho-Corasick → `1C` Bounded Regex), a quarantined schema-only Layer 2 intent extractor (`Gemini` / `Ollama` / `Heuristic`), and a pure deterministic Layer 3 RBAC/ABAC/authority policy gate.
- **Layer 4 Origin Gate (`app/provenance.py`):** Paired text-level scanning (L1–L3) with provenance/taint tracking (`origin` and `arg_origins`) plus Meta's Rule of Two before any tool executes.
- **Vector store:** an in-process dense+BM25+RRF store (`app/rag/store.py`), rebuilt from the KB on start. The access filter (public, or private + owner == session customer) lives in the store.
- **Embeddings:** FastEmbed (`bge-small-en-v1.5` + bm25 + MiniLM reranker) when the `app` extra is installed; otherwise a deterministic hashing embedding + lexical reranker so retrieval runs offline.
- **No orchestration framework:** the chat pipeline is a hand-written sequence of nodes in `app/pipeline.py` with a tiny runner (timings + live progress events).
- **Scan transport:** the app reaches the Shield over HTTP `/scan`, falling back to an in-process funnel when the Shield service is down (so ingestion/tests run standalone).
- **Parser default:** `pymupdf` (fast, CI), `docling` opt-in via the `docling` extra and `PARSER=docling` (heavier, OCR + tables).
- **Auth:** demo-grade signed cookies via `itsdangerous`, no passwords. Admin endpoints use a static `X-Admin-Token`. Stated as demo-grade in the README.
- **Prices:** `shared/pricing.py` holds placeholder per-token prices; verify against current pricing before quoting cost numbers.
