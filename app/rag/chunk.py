"""Heading-aware chunking.

- cut Markdown into sections at headings, keeping a heading path
  (e.g. "Warranty > Exclusions");
- keep tables whole; split an over-long table by rows, repeating the header;
- split long sections with a recursive splitter (~800 chars, 120 overlap);
- each chunk keeps doc_id, page(s), heading_path and kind (text|table).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
CHUNK_CHARS = 800
CHUNK_OVERLAP = 120
MAX_TABLE_CHARS = 1200


@dataclass
class RawChunk:
    text: str
    heading_path: str
    page: int
    kind: str = "text"  # text | table


def _recursive_split(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    # prefer paragraph, then sentence, then hard cut
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        window = text[start:end]
        if end < len(text):
            br = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if br > size * 0.5:
                end = start + br + 1
                window = text[start:end]
        out.append(window.strip())
        start = max(end - overlap, end) if end >= len(text) else end - overlap
    return [c for c in out if c]


def _split_table(block: str, heading_path: str, page: int) -> list[RawChunk]:
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0]
    sep = lines[1] if len(lines) > 1 and set(lines[1].replace("|", "").strip()) <= {"-", " ", ":"} else None
    body = lines[(2 if sep else 1):]
    chunks, cur, cur_len = [], [], 0
    base_head = [header] + ([sep] if sep else [])
    _ = base_head  # header lines kept with each split
    for row in body:
        if cur_len + len(row) > MAX_TABLE_CHARS and cur:
            chunks.append(RawChunk("\n".join(base_head + cur), heading_path, page, "table"))
            cur, cur_len = [], 0
        cur.append(row)
        cur_len += len(row)
    if cur:
        chunks.append(RawChunk("\n".join(base_head + cur), heading_path, page, "table"))
    if not chunks:  # just a header
        chunks.append(RawChunk(block, heading_path, page, "table"))
    return chunks


def _heading_path(stack: list[tuple[int, str]]) -> str:
    return " > ".join(h for _, h in stack)


def _flush(chunks: list[RawChunk], buffer: list[str], hp: str, page_number: int) -> None:
    block = "\n".join(buffer).strip()
    if block:
        for piece in _recursive_split(block):
            chunks.append(RawChunk(piece, hp, page_number, "text"))


def chunk_pages(pages: list) -> list[RawChunk]:
    """pages: list of objects with .number and .text (parse.Page)."""
    chunks: list[RawChunk] = []
    heading_stack: list[tuple[int, str]] = []

    for page in pages:
        page_number = page.number
        lines = page.text.splitlines()
        i = 0
        buffer: list[str] = []

        while i < len(lines):
            line = lines[i]
            m = HEADING.match(line)
            if m:
                _flush(chunks, buffer, _heading_path(heading_stack), page_number)
                buffer = []
                level = len(m.group(1))
                title = m.group(2).strip()
                heading_stack[:] = [(lv, h) for lv, h in heading_stack if lv < level]
                heading_stack.append((level, title))
                i += 1
                continue
            if TABLE_ROW.match(line):
                _flush(chunks, buffer, _heading_path(heading_stack), page_number)
                buffer = []
                tbl = []
                while i < len(lines) and TABLE_ROW.match(lines[i]):
                    tbl.append(lines[i])
                    i += 1
                chunks.extend(_split_table("\n".join(tbl), _heading_path(heading_stack), page_number))
                continue
            buffer.append(line)
            i += 1
        _flush(chunks, buffer, _heading_path(heading_stack), page_number)
    return chunks
