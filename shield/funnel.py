"""The 3-Layer Zero-Judge Security Funnel.

Architecture:
  Layer 1: 3-Stage Deterministic Funnel (1A Normalizer -> 1B Aho-Corasick -> 1C Targeted Regex)
  Layer 2: Quarantined Intent Extractor & Neutralizer (Schema-enforced JSON, zero tool access)
  Layer 3: Deterministic Policy & Symbolic Gate (Zero AI, pure deterministic RBAC + ABAC + Authority checks)

Never uses trained numeric classifiers or LLM judges.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from shared.schemas import Decision, Layer, Source, Verdict
from shield.intent_extractor import IntentExtractor
from shield.policy_gate import AuthContext, PolicyGate
from shield.regex_layer import RegexLayer

logger = logging.getLogger("shield.funnel")


def _preview(text: str, n: int = 200) -> str:
    s = " ".join(text.split())
    return s[:n] + ("…" if len(s) > n else "")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VerdictCache:
    """In-memory TTL cache for funnel decisions."""

    def __init__(self, ttl_seconds: float = 300.0):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> dict | None:
        row = self._store.get(key)
        if not row:
            self.misses += 1
            return None
        ts, val = row
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return val

    def set(self, key: str, val: dict) -> None:
        self._store[key] = (time.time(), val)


class Funnel:
    """The 3-Layer Zero-Judge Security Pipeline."""

    def __init__(
        self,
        regex: RegexLayer | None = None,
        layer1: RegexLayer | None = None,
        intent_extractor: IntentExtractor | None = None,
        layer2: IntentExtractor | None = None,
        policy_gate: PolicyGate | None = None,
        layer3: PolicyGate | None = None,
        # Legacy parameters preserved for smooth migration
        classifier: Any = None,
        judge: Any = None,
        chat_fail_mode: str = "open",
        doc_fail_mode: str = "closed",
        cache: VerdictCache | None = None,
    ):
        self.layer1 = layer1 or regex or RegexLayer()
        self.regex = self.layer1  # backward compatibility alias
        self.layer2 = layer2 or intent_extractor or IntentExtractor()
        self.intent_extractor = self.layer2
        self.layer3 = layer3 or policy_gate or PolicyGate()
        self.policy_gate = self.layer3

        self.chat_fail_mode = chat_fail_mode
        self.doc_fail_mode = doc_fail_mode
        self.cache = cache or VerdictCache()

    def _fail_mode_for(self, source: Source) -> str:
        return self.doc_fail_mode if source == Source.document else self.chat_fail_mode

    def _base_decision(self, text: str, source: Source) -> Decision:
        return Decision(
            source=source,
            text_preview=_preview(text),
            text_sha256=_sha256(text),
        )

    def _cache_key(
        self,
        text_sha256: str,
        source: Source,
        auth_context: AuthContext | None,
        layers: list[Layer] | None,
        fail_mode: str,
    ) -> str:
        role = auth_context.role.lower().strip() if auth_context else "user"
        cid = str(auth_context.customer_id) if auth_context else "1"
        layer_key = ",".join(sorted(l.value for l in layers)) if layers is not None else "all"
        return f"{text_sha256}:{source.value}:{role}:{cid}:{layer_key}:{fail_mode}"

    def check(
        self,
        text: str,
        source: Source = Source.user,
        context: list[str] | None = None,
        layers: list[Layer] | None = None,
        fail_mode: str | None = None,
        on_step=None,
        auth_context: AuthContext | None = None,
    ) -> Decision:
        """Run the 3-Layer Security Pipeline on input text.

        `on_step(layer, status, detail)` is called as each layer executes.
        """
        context = context or []
        t0 = time.perf_counter()
        d = self._base_decision(text, source)
        fmode = fail_mode or self._fail_mode_for(source)

        cache_key = self._cache_key(d.text_sha256, source, auth_context, layers, fmode)
        if on_step is None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                res_d = Decision.model_validate(cached)
                res_d.id = uuid.uuid4().hex[:16]
                res_d.ts = time.time()
                res_d.chunk_id = None
                res_d.latency_ms = round((time.perf_counter() - t0) * 1000, 3)
                return res_d

        def step(layer: str, status: str, detail: str = "") -> None:
            if on_step:
                try:
                    on_step(layer, status, detail)
                except Exception:
                    pass

        run_l1 = (layers is None) or (Layer.layer1 in layers) or (Layer.regex in layers)
        run_l2 = (layers is None) or (Layer.layer2 in layers) or (Layer.classifier in layers)
        run_l3 = (layers is None) or (Layer.layer3 in layers) or (Layer.judge in layers)

        # ------------------------------------------------------------------- #
        # Layer 1: 3-Stage Deterministic Security Funnel
        # ------------------------------------------------------------------- #
        normalized_text = text
        if run_l1:
            if hasattr(self.layer1, "scan"):
                res = self.layer1.scan(text)
                bundle = res.inspection_bundle
                if res.normalized_text:
                    normalized_text = res.normalized_text
                elif bundle and bundle.canonical_text:
                    normalized_text = bundle.canonical_text

                # Stage 1A: Canonicalization & De-obfuscation
                s1a_blocked = res.stage_triggered == "stage_1a"
                s1a_detail = (
                    f"rule {res.primary_match.rule_id} ({res.primary_match.owasp_ref})"
                    if s1a_blocked and res.primary_match
                    else (
                        f"unpacked {len(bundle.decoded_payloads)} payload(s) · {', '.join(bundle.obfuscation_signals)}"
                        if bundle and bundle.obfuscation_signals
                        else "canonicalized NFKC · zero-width & bidi clean"
                    )
                )
                step("stage_1a", "block" if s1a_blocked else "pass", s1a_detail)

                # Stage 1B: Aho-Corasick Multi-Pattern Scan
                s1b_blocked = res.stage_triggered == "stage_1b"
                s1b_detail = (
                    f"matched signature '{res.primary_match.matched_span}' ({res.primary_match.owasp_ref})"
                    if s1b_blocked and res.primary_match
                    else "not reached"
                    if s1a_blocked
                    else f"{len(self.layer1.funnel.aho_corasick)} threat signatures checked · clean"
                )
                step("stage_1b", "block" if s1b_blocked else "skip" if s1a_blocked else "pass", s1b_detail)

                # Stage 1C: Targeted ReDoS-Safe Regex Engine
                s1c_blocked = res.stage_triggered == "stage_1c"
                s1c_detail = (
                    f"matched rule {res.primary_match.rule_id} ({res.primary_match.owasp_ref})"
                    if s1c_blocked and res.primary_match
                    else "not reached"
                    if (s1a_blocked or s1b_blocked)
                    else f"{len(self.layer1.funnel.targeted_regex)} bounded regex rules checked · no rule matched"
                )
                step("stage_1c", "block" if s1c_blocked else "skip" if (s1a_blocked or s1b_blocked) else "pass", s1c_detail)

                primary = res.primary_match
                step("regex", "block" if res.blocked else "pass",
                     f"rule {primary.rule_id} ({primary.owasp_ref})" if res.blocked and primary else "3-stage deterministic funnel · clean")

                if res.blocked and primary:
                    d.verdict = Verdict.block
                    d.layer = Layer.layer1
                    d.owasp = primary.owasp_ref
                    d.rule_id = primary.rule_id
                    d.reason = primary.why
                    d.latency_ms = (time.perf_counter() - t0) * 1000
                    self.cache.set(cache_key, d.model_dump(mode="json"))
                    return d
            else:
                step("regex", "start", "matching injection rules")
                hit = self.layer1.check(text)
                step("regex", "block" if hit else "pass",
                     f"rule {hit.rule_id} ({hit.owasp})" if hit else "no rule matched")
                if hit:
                    d.verdict = Verdict.block
                    d.layer = Layer.layer1
                    d.owasp = hit.owasp
                    d.rule_id = hit.rule_id
                    d.reason = hit.why
                    d.latency_ms = (time.perf_counter() - t0) * 1000
                    self.cache.set(cache_key, d.model_dump(mode="json"))
                    return d

        if not run_l2 and not run_l3:
            d.verdict = Verdict.allow
            d.layer = Layer.layer1 if run_l1 else Layer.none
            d.reason = "Layer 1 passed (downstream layers skipped)"
            d.latency_ms = (time.perf_counter() - t0) * 1000
            self.cache.set(cache_key, d.model_dump(mode="json"))
            return d

        # ------------------------------------------------------------------- #
        # Layer 2: Quarantined Intent Extractor & Neutralizer
        # ------------------------------------------------------------------- #
        step("layer2", "start", "extracting schema-enforced intents (zero-tool quarantine)")
        ext = self.layer2.extract(normalized_text)
        d.layer2_extraction = ext

        intent_names = [it.intent for it in ext.intents] if ext.intents else ["general_faq"]
        intents_str = ", ".join(intent_names)
        summary = (ext.intents[0].neutral_summary if ext.intents else "neutralized")[:60]
        step("layer2", "pass" if not ext.extraction_failed else "warn",
             f"extracted [{intents_str}] · {summary} ({ext.provider_used})")

        if not run_l3:
            d.verdict = Verdict.allow
            d.layer = Layer.layer2
            d.reason = f"Layer 2 extracted [{intents_str}]"
            d.latency_ms = (time.perf_counter() - t0) * 1000
            self.cache.set(cache_key, d.model_dump(mode="json"))
            return d

        # ------------------------------------------------------------------- #
        # Layer 3: Deterministic Policy & Symbolic Gate
        # ------------------------------------------------------------------- #
        step("layer3", "start", "evaluating deterministic RBAC, ABAC & authority invariants")
        pol = self.layer3.evaluate(ext, auth_context)
        d.policy_result = pol
        d.latency_ms = (time.perf_counter() - t0) * 1000

        if pol.verdict == Verdict.block:
            if fmode == "open" and pol.rule_id == "POL_EXTRACTION_FAILED":
                d.verdict = Verdict.allow
                d.layer = Layer.layer3
                d.reason = "Layer 2 extraction failed (fail-open for chat)"
                step("layer3", "warn", d.reason)
                self.cache.set(cache_key, d.model_dump(mode="json"))
                return d
            d.verdict = Verdict.block
            d.layer = Layer.layer3
            d.rule_id = pol.rule_id
            d.owasp = pol.owasp
            d.reason = pol.reason
            step("layer3", "block", f"[{pol.rule_id}] {pol.reason}")
            self.cache.set(cache_key, d.model_dump(mode="json"))
            return d

        d.verdict = Verdict.allow
        d.layer = Layer.layer3
        d.reason = pol.reason
        step("layer3", "pass", f"allowed · {pol.reason}")
        self.cache.set(cache_key, d.model_dump(mode="json"))
        return d
