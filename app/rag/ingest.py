"""Secure ingestion (Flow B). No LLM reads a chunk before it passes the scan.

parse -> hidden-text flag -> normalise -> heading-aware split -> SCAN every
chunk through the funnel (source=document, fail-closed) -> enrich clean chunks
only (optional) -> decide per document -> store clean chunks / quarantine bad
ones. Document-level quarantine if >=30% chunks flagged or any chunk >= 0.98.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app import db
from app.rag import chunk as chunker
from app.rag import contextualize
from app.rag import parse as parser
from app.rag.store import Chunk, get_store
from app.scanner import get_scanner
from app.settings import SETTINGS
from shared.schemas import Decision, ScanItem, Source, Verdict

DOC_QUARANTINE_FRACTION = 0.30
DOC_QUARANTINE_SCORE = 0.98


@dataclass
class IngestResult:
    doc_id: str
    status: str  # ready | partial | quarantined
    chunks_total: int = 0
    chunks_indexed: int = 0
    chunks_quarantined: int = 0
    chunks_enriched: int = 0  # Contextual Retrieval blurbs added (Ollama)
    decisions: list[Decision] = field(default_factory=list)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _clear_doc(doc_id: str) -> None:
    """Remove any prior sections, quarantine rows and vectors for a doc_id."""
    get_store().clear_doc(doc_id)
    with db.Session() as s:
        s.query(db.Section).filter(db.Section.doc_id == doc_id).delete()
        s.query(db.Quarantine).filter(db.Quarantine.doc_id == doc_id).delete()
        s.commit()


def ingest_file(
    path: str | Path,
    owner: str,
    doc_title: str | None = None,
    visibility: str = "private",
    parser_name: str | None = None,
    doc_id: str | None = None,
    on_event=None,
    dedupe: bool = True,
) -> IngestResult:
    """`on_event(dict)` (optional) reports live progress: parse, per-chunk scan
    verdicts and the final status, so the chat can show the scan as it runs."""
    def emit(**ev) -> None:
        if on_event:
            try:
                on_event(ev)
            except Exception:  # noqa: BLE001 - progress never breaks ingestion
                pass

    path = Path(path)
    parser_name = parser_name or SETTINGS.parser
    doc_id = doc_id or uuid.uuid4().hex[:16]
    title = doc_title or path.name
    sha = file_sha256(path)

    # Dedupe: same owner + same bytes -> return the existing doc, re-index nothing.
    with db.Session() as s:
        existing = (
            s.query(db.Document)
            .filter(db.Document.owner == str(owner), db.Document.sha256 == sha)
            .first()
        )
        if dedupe and existing and existing.id != doc_id:
            return IngestResult(
                doc_id=existing.id, status=existing.status,
                chunks_total=existing.chunks_total, chunks_indexed=existing.chunks_indexed,
            )

    # Idempotent re-index: clear any prior rows/vectors for this doc_id.
    _clear_doc(doc_id)

    parsed = parser.parse(path, parser=parser_name)
    # normalise text per page and keep the hidden-text flag
    for pg in parsed.pages:
        pg.text = parser.normalise(pg.text)

    raw_chunks = chunker.chunk_pages(parsed.pages)
    hidden_pages = {pg.number for pg in parsed.pages if pg.hidden_text}
    emit(stage="parse", pages=len(parsed.pages), parsed_by=parsed.parsed_by,
         hidden_pages=sorted(hidden_pages), chunks=len(raw_chunks))

    # Build scan items; also scan decoded base64 as extra text.
    scanner = get_scanner()
    items: list[ScanItem] = []
    for idx, rc in enumerate(raw_chunks):
        cid = f"{doc_id}:c{idx}"
        text = rc.text
        for dec in parser.decoded_base64_segments(rc.text):
            text += "\n[decoded-base64] " + dec
        items.append(ScanItem(id=cid, text=text, source=Source.document))

    from contextlib import nullcontext

    from shared import byok

    if on_event:
        decisions = []
        for i, it in enumerate(items):
            emit(stage="scan_start", i=i, total=len(items))
            guard = byok.disable_server_key() if (SETTINGS.public_demo and not byok.current() and i >= 10) else nullcontext()
            with guard:
                d = scanner.scan([it], fail_mode="closed")[0]
            decisions.append(d)
            emit(stage="scan", i=i, total=len(items), verdict=d.verdict.value, layer=d.layer.value,
                 score=d.score, owasp=d.owasp, reason=d.reason[:160],
                 hidden=raw_chunks[i].page in hidden_pages, page=raw_chunks[i].page,
                 preview=raw_chunks[i].text[:110])
    else:
        if SETTINGS.public_demo and not byok.current() and len(items) > 10:
            decisions = scanner.scan(items[:10], fail_mode="closed")
            with byok.disable_server_key():
                decisions += scanner.scan(items[10:], fail_mode="closed")
        else:
            decisions = scanner.scan(items, fail_mode="closed") if items else []

    store = get_store()
    clean: list[Chunk] = []
    quarantined: list[tuple[chunker.RawChunk, Decision]] = []
    max_score = 0.0

    for rc, d in zip(raw_chunks, decisions):
        if d.score is not None:
            max_score = max(max_score, d.score)
        is_hidden = rc.page in hidden_pages
        if d.verdict == Verdict.block or (is_hidden and (d.score or 0) >= 0.5):
            quarantined.append((rc, d))
        else:
            clean.append(
                Chunk(
                    chunk_id=d.chunk_id or f"{doc_id}:{len(clean)}",
                    doc_id=doc_id,
                    doc_title=title,
                    page=rc.page,
                    heading_path=rc.heading_path,
                    owner=str(owner),
                    visibility=visibility,
                    text=rc.text,
                    kind=rc.kind,
                )
            )

    total = len(raw_chunks)
    frac_flagged = (len(quarantined) / total) if total else 0.0
    doc_quarantined = frac_flagged >= DOC_QUARANTINE_FRACTION or max_score >= DOC_QUARANTINE_SCORE

    if doc_quarantined:
        # quarantine everything
        quarantined = list(zip(raw_chunks, decisions)) if decisions else []
        clean = []

    # persist
    with db.Session() as s:
        for rc, d in quarantined:
            s.add(
                db.Quarantine(
                    doc_id=doc_id,
                    chunk_id=d.chunk_id or f"{doc_id}:q",
                    text=rc.text[:4000],
                    score=d.score,
                    layer=d.layer.value,
                    owasp=d.owasp,
                    reason=d.reason[:400],
                    hidden_text=1 if rc.page in hidden_pages else 0,
                )
            )
        for c in clean:
            s.add(
                db.Section(
                    id=c.chunk_id, doc_id=doc_id, heading_path=c.heading_path,
                    text=c.text, page=c.page,
                )
            )
        s.commit()

    # Contextual Retrieval: enrich ONLY clean chunks (they already passed the
    # scan) with an Ollama-written situating blurb used for indexing. No-op when
    # disabled/unavailable. This is the first time an LLM sees the content.
    enriched = 0
    if clean:
        doc_text = "\n\n".join(pg.text for pg in parsed.pages)
        enriched = contextualize.contextualize(doc_text, clean)
        store.upsert(clean)

    status = "quarantined" if doc_quarantined else ("partial" if quarantined else "ready")

    with db.Session() as s:
        row = s.get(db.Document, doc_id)
        if row is None:
            row = db.Document(
                id=doc_id, owner=str(owner), filename=title,
                sha256=file_sha256(path), status=status, visibility=visibility,
            )
            s.add(row)
        row.status = status
        row.parsed_by = parsed.parsed_by
        row.chunks_total = total
        row.chunks_indexed = len(clean)
        row.progress = "done"
        s.commit()

    return IngestResult(
        doc_id=doc_id,
        status=status,
        chunks_total=total,
        chunks_indexed=len(clean),
        chunks_quarantined=len(quarantined),
        chunks_enriched=enriched,
        decisions=decisions,
    )
