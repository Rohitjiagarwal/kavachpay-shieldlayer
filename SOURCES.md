# Open-Source Sources, Standards & Attributions

This document records the open-source libraries, public security standards, and published research patterns used across **ShieldLayer** and the **KavachPay** reference application.

ShieldLayer is designed as a vendor-neutral, zero-judge security pipeline whose core detection and policy enforcement run entirely on open-source software and open standards—with optional local open-weight models (via Ollama) or deterministic heuristics so no proprietary API is required.

---

## 1. Security Pipeline Layers & Conceptual Sources

### Layer 1 — 3-Stage Deterministic Security Funnel
**Code:** [`shield/layer1_funnel.py`](shield/layer1_funnel.py), [`shield/normalizer.py`](shield/normalizer.py), [`shield/aho_corasick_engine.py`](shield/aho_corasick_engine.py), [`shield/targeted_regex_engine.py`](shield/targeted_regex_engine.py), [`rules/`](rules/)

| Sub-stage | Technique / Algorithm | Open-Source / Public Source |
|---|---|---|
| **Stage 1A: Canonicalization & De-obfuscation** | Unicode NFKC normalization (`unicodedata.normalize`) | Python Standard Library & Unicode Standard Annex #15 |
| | Invisible character & Bidi override stripping | Unicode Bidirectional Algorithm; Trojan Source defense ([Boucher & Anderson, 2021](https://trojansource.codes/)) |
| | Confusable / homoglyph resolution | Unicode Technical Standard #39 (Confusables); [`confusable-homoglyphs`](https://pypi.org/project/confusable-homoglyphs/) (MIT) |
| | Recursive URL, Hex, HTML entity, and Base64 unpacking | Python Standard Library (`urllib.parse`, `html`, `base64`) |
| **Stage 1B: Multi-Pattern Gate** | Aho–Corasick $O(n)$ string-matching automaton | Aho & Corasick (1975); [`pyahocorasick`](https://pypi.org/project/pyahocorasick/) (BSD-3-Clause) |
| **Stage 1C: Targeted Regex Engine** | Bounded-quantifier, ReDoS-safe structural regex matching | Python Standard Library (`re`), configured in [`rules/regex_rules.yaml`](rules/regex_rules.yaml) |

**Threat Taxonomies (Open Community Standards):**
- **OWASP Top 10 for LLM Applications (2025):** `LLM01` (Prompt Injection), `LLM02` (Sensitive Information Disclosure), `LLM05` (Improper Output Handling), `LLM06` (Excessive Agency), `LLM07` (System Prompt Leakage), `LLM09` (Misinformation), `LLM10` (Unbounded Consumption).
- **OWASP Top 10 for Agentic Applications:** `ASI01` (Agent Goal Hijacking), `ASI02` (Tool Misuse & Parameter Tampering), `ASI06` (Compliance & Procedure Fraud).
- **MITRE ATLAS:** `AML.T0051` (LLM Prompt Injection), `AML.T0054` (LLM Jailbreak), `AML.T0057` (LLM Data Exfiltration / System Abuse).

---

### Layer 2 — Quarantined Intent Extractor & Neutralizer
**Code:** [`shield/intent_extractor.py`](shield/intent_extractor.py), [`shield/layer2_providers.py`](shield/layer2_providers.py), [`config/intent_catalog.yaml`](config/intent_catalog.yaml)

- **Architectural Pattern:**
  - **Dual-LLM / Quarantined LLM Pattern:** Isolating an untrusted-input parser with zero tool access and strict structured output ([Simon Willison, 2023](https://simonwillison.net/2023/Apr/25/dual-llm-pattern/)).
  - **Capability & Control/Data Separation:** Separating untrusted data parsing from privileged execution as formalized in **CaMeL** ([Debenedetti et al., 2025](https://arxiv.org/abs/2503.18813), *"Defeating Prompt Injections by Design"*).
- **Local / Open-Source Runtimes:**
  - **Heuristic Extractor (`HeuristicProvider`):** Pure Python deterministic pattern & keyword mapping against [`config/intent_catalog.yaml`](config/intent_catalog.yaml) (zero external models or network calls).
  - **Ollama Adapter (`OllamaProvider`):** Local inference with open-weight models (default `qwen2.5:3b` via [Ollama](https://ollama.com/), MIT) using native JSON schema output at `temperature=0.0`.
  - **Optional Cloud Adapter (`GeminiProvider`):** Optional Google Gemini REST adapter for hosted demos when `GEMINI_API_KEY` is supplied; not required to run ShieldLayer.

---

### Layer 3 — Deterministic Policy & Symbolic Gate
**Code:** [`shield/policy_gate.py`](shield/policy_gate.py), [`config/intent_catalog.yaml`](config/intent_catalog.yaml)

- **Access Control Models:** Classic **RBAC** (Role-Based Access Control) and **ABAC** (Attribute-Based Access Control) evaluated deterministically in pure Python against verified session identity (`AuthContext`) and YAML-defined intent policies (`PyYAML`, MIT).
- **Symbolic Invariants:**
  - Fail-closed extraction check (`POL_EXTRACTION_FAILED`)
  - Authority spoofing check (`POL_AUTHORITY_SPOOFING` — OWASP `ASI01`, MITRE `AML.T0054`)
  - Multi-intent smuggling check (`POL_INTENT_SMUGGLING` — OWASP `ASI01`)
  - Role & tenant ownership checks (`POL_RBAC_VIOLATION`, `POL_ABAC_VIOLATION` — OWASP `ASI02`)

---

### Layer 4 — Provenance & Origin Gate (Application-Level Defense)
**Code:** [`app/provenance.py`](app/provenance.py), [`app/pipeline.py`](app/pipeline.py)

- **Rule of Two:** Require explicit human confirmation once a session ingests untrusted external content ([Meta AI Security, 2025](https://ai.meta.com/blog/practical-ai-agent-security/)).
- **Provenance & Taint Tracking:** Separating principal identity (`user`, `admin`) and argument provenance (`database`, `document`, `tool`, `model`) rather than relying solely on text detectors, motivated by adaptive attacks against prompt-injection detectors ([Nasr, Carlini et al., 2025](https://arxiv.org/abs/2510.09023)).

---

## 2. Third-Party Open-Source Dependencies

### Python Backend ([`pyproject.toml`](pyproject.toml))
| Package | Role | License |
|---|---|---|
| `fastapi` | HTTP API framework | MIT |
| `uvicorn` | ASGI server | BSD-3-Clause |
| `pydantic` | Schema validation & contracts | MIT |
| `pyyaml` | YAML rules & intent catalog parsing | MIT |
| `httpx` | HTTP client (Ollama / optional APIs) | BSD-3-Clause |
| `python-multipart` | File upload parsing | Apache-2.0 |
| `numpy` | Vector math for RAG | BSD-3-Clause |
| `rich` | CLI scorecard formatting | MIT |
| `pyahocorasick` | Stage 1B Aho–Corasick automaton | BSD-3-Clause |
| `confusable-homoglyphs` | Unicode confusable detection support | MIT |
| `sqlalchemy` | SQLite ORM (`app` extra) | MIT |
| `itsdangerous` | Signed demo session cookies (`app` extra) | BSD-3-Clause |
| `fastembed` | Local dense/BM25 embeddings & reranking (`app` extra) | Apache-2.0 |
| `python-docx` | DOCX parsing (`app` extra) | MIT |
| `pymupdf` | PDF parsing & hidden-text inspection (`app` extra) | **AGPL-3.0** *(note for commercial redistribution; swap for BSD/MIT PDF parser such as `pypdf` if permissive-only licensing is required)* |
| `docling` | Optional layout/OCR document parser (`docling` extra) | MIT |

### Dashboard Frontend ([`dashboard/package.json`](dashboard/package.json))
| Package | Role | License |
|---|---|---|
| `next` | React web framework | MIT |
| `react` / `react-dom` | UI rendering | MIT |
| `recharts` | Scorecard charts | MIT |
| `tailwindcss` / `postcss` / `autoprefixer` | Styling | MIT |
| `typescript` / `vitest` | Typechecking & frontend tests | Apache-2.0 / MIT |

---

## 3. Legacy Fixtures

[`attacks/fixtures/legacy_lumora/`](attacks/fixtures/legacy_lumora/) and `lumora.example` in [`app/output_checks.py`](app/output_checks.py) are fictional test fixtures from an earlier demo domain before KavachPay.
