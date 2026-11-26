"""Output checks applied to every answer before it reaches the customer.

- canary check: any planted secret in the reply => refusal (LLM07/LLM02)
- PII mask: mask emails/phones that are not this customer's
- markdown sanitiser: strip images and links to non-allowlisted domains (LLM05)
- citation check: drop [cN] ids that were not actually sent
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ALLOWED_LINK_DOMAINS = {"lumora.example", "localhost"}

_EMAIL = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I)
_PHONE = re.compile(r"\b(?:\+?\d[\s-]?){9,}\d\b")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_CITE = re.compile(r"\[c(\d+)\]")

REFUSAL = (
    "I can't share that. If you think this is a mistake, I can open a ticket for "
    "a human to help."
)


@dataclass
class CheckResult:
    text: str
    refused: bool = False
    events: list[str] = field(default_factory=list)  # owasp ids logged


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    host = m.group(1).lower() if m else ""
    return host.split(":")[0]


def run_output_checks(
    text: str,
    canaries: list[str],
    allowed_citations: set[int],
    customer_contacts: set[str],
) -> CheckResult:
    events: list[str] = []

    # 1) canary — any leak is a hard refusal
    for c in canaries:
        if c and c in text:
            return CheckResult(text=REFUSAL, refused=True, events=["LLM07"])

    # 2) PII mask (keep this customer's own contacts)
    def mask_email(m: re.Match) -> str:
        v = m.group(0)
        return v if v.lower() in customer_contacts else "[email hidden]"

    def mask_phone(m: re.Match) -> str:
        v = m.group(0)
        digits = re.sub(r"\D", "", v)
        return v if any(digits in re.sub(r"\D", "", c) for c in customer_contacts) else "[phone hidden]"

    new = _EMAIL.sub(mask_email, text)
    new = _PHONE.sub(mask_phone, new)
    if new != text:
        events.append("LLM02")
    text = new

    # 3) markdown sanitiser — drop images; drop links to non-allowlisted domains
    if _MD_IMAGE.search(text):
        text = _MD_IMAGE.sub("[image removed]", text)
        events.append("LLM05")

    def link_sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if _domain(url) in ALLOWED_LINK_DOMAINS:
            return m.group(0)
        return label  # keep the text, drop the link

    new = _MD_LINK.sub(link_sub, text)
    if new != text:
        if "LLM05" not in events:
            events.append("LLM05")
    text = new

    # 4) citation check — remove unknown [cN]
    def cite_sub(m: re.Match) -> str:
        n = int(m.group(1))
        return m.group(0) if n in allowed_citations else ""

    new = _CITE.sub(cite_sub, text)
    if new != text:
        events.append("LLM09")
    text = new

    return CheckResult(text=text, refused=False, events=events)
