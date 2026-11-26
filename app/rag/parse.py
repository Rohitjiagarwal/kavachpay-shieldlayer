"""Parse an uploaded file into pages of Markdown-ish text, with a hidden-text
check and Unicode normalisation.

Parsers:
  pymupdf (default/fast): PyMuPDF for PDF, python-docx for DOCX, plain read for
                          TXT/MD. No OCR, no table structure.
  docling (optional):     layout + tables + OCR (heavy; pulls in torch).

TXT and MD always work with no extra dependency, which keeps the ingestion
pipeline testable offline.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


@dataclass
class Page:
    number: int
    text: str
    hidden_text: bool = False


@dataclass
class ParsedDoc:
    pages: list[Page] = field(default_factory=list)
    parsed_by: str = ""


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(ZERO_WIDTH)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_B64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])")


def decoded_base64_segments(text: str) -> list[str]:
    """Return decoded text for base64-looking segments, for extra scanning."""
    import base64

    out = []
    for m in _B64.finditer(text):
        try:
            dec = base64.b64decode(m.group(0), validate=True).decode("utf-8", "ignore")
            if dec and sum(c.isprintable() for c in dec) / max(1, len(dec)) > 0.8:
                out.append(dec)
        except Exception:  # noqa: BLE001
            continue
    return out


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_pdf_pymupdf(path: Path) -> list[Page]:
    import fitz  # type: ignore  (PyMuPDF)

    pages = []
    doc = fitz.open(path)
    for i, page in enumerate(doc):
        text = page.get_text("text")
        hidden = _pdf_hidden_text(page)
        pages.append(Page(number=i + 1, text=text, hidden_text=hidden))
    return pages


def _pdf_hidden_text(page) -> bool:
    """Flag white, tiny (<4pt) or off-page text — common injection hiding spots."""
    try:
        rect = page.rect
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 12)
                    color = span.get("color", 0)
                    bbox = span.get("bbox", (0, 0, 0, 0))
                    white = color == 16777215  # 0xFFFFFF
                    tiny = size < 4
                    offpage = bbox[1] > rect.height or bbox[3] < 0 or bbox[0] > rect.width
                    if (white or tiny or offpage) and span.get("text", "").strip():
                        return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _parse_docx(path: Path) -> list[Page]:
    import docx  # type: ignore

    d = docx.Document(str(path))
    parts = []
    for p in d.paragraphs:
        style = (p.style.name or "").lower() if p.style else ""
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            parts.append("#" * int(level) + " " + p.text)
        elif p.text.strip():
            parts.append(p.text)
    for table in d.tables:
        rows = [" | ".join(c.text for c in r.cells) for r in table.rows]
        parts.append("\n".join(rows))
    return [Page(number=0, text="\n\n".join(parts))]


def parse(path: str | Path, parser: str = "pymupdf") -> ParsedDoc:
    path = Path(path)
    ext = path.suffix.lower()

    if parser == "docling" and ext in {".pdf", ".docx", ".png", ".jpg", ".jpeg"}:
        try:
            return _parse_docling(path, ext)
        except Exception:  # noqa: BLE001
            parser = "pymupdf"  # fall back if docling unavailable

    if ext in {".txt", ".md"}:
        return ParsedDoc(pages=[Page(number=0, text=_read_text(path))], parsed_by="plain")
    if ext == ".pdf":
        return ParsedDoc(pages=_parse_pdf_pymupdf(path), parsed_by="pymupdf")
    if ext == ".docx":
        return ParsedDoc(pages=_parse_docx(path), parsed_by="pymupdf")
    # treat unknown as text
    return ParsedDoc(pages=[Page(number=0, text=_read_text(path))], parsed_by="plain")


def _pdf_hidden_pages(path: Path) -> set[int]:
    """Run PyMuPDF's hidden-text forensics even when Docling does the parse.

    Docling gives better structure (reading order, tables) but exporting to
    Markdown discards font colour/size/position — exactly the signals a document
    injection hides behind (white or 1pt text, off-page glyphs). We keep that
    check as a cheap pre-pass so the security property survives the parser swap.
    """
    try:
        import fitz  # type: ignore
    except Exception:  # noqa: BLE001
        return set()
    hidden: set[int] = set()
    try:
        doc = fitz.open(path)
        for i, page in enumerate(doc):
            if _pdf_hidden_text(page):
                hidden.add(i + 1)
    except Exception:  # noqa: BLE001
        return hidden
    return hidden


def _parse_docling(path: Path, ext: str) -> ParsedDoc:
    """Structure-aware parse via Docling: reading order, headings and tables
    (rendered as Markdown, which the heading-aware chunker then keeps whole).

    We split the exported Markdown back into pages on Docling's page markers
    when present, and merge in PyMuPDF's hidden-text flags for PDFs so a
    white-text injection in a Docling-parsed PDF is still quarantined.
    """
    from docling.document_converter import DocumentConverter  # type: ignore

    conv = DocumentConverter()
    result = conv.convert(str(path))
    document = result.document

    # Per-page Markdown when Docling exposes page numbers; else one page.
    pages: list[Page] = []
    page_ids: list[int] = []
    try:
        page_ids = sorted(int(p) for p in document.pages.keys())
    except Exception:  # noqa: BLE001
        page_ids = []

    rendered = False
    if page_ids:
        try:
            for pno in page_ids:
                md = document.export_to_markdown(page_no=pno)
                if md and md.strip():
                    pages.append(Page(number=pno, text=md))
            rendered = bool(pages)
        except Exception:  # noqa: BLE001  (older docling: no page_no kwarg)
            pages, rendered = [], False

    if not rendered:
        pages = [Page(number=1, text=document.export_to_markdown())]

    if ext == ".pdf":
        hidden = _pdf_hidden_pages(path)
        for pg in pages:
            if pg.number in hidden or (len(pages) == 1 and hidden):
                pg.hidden_text = True

    return ParsedDoc(pages=pages, parsed_by="docling")
