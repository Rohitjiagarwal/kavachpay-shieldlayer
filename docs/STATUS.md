# Status

What is built and verified (2026-11-26).

| Area | State |
|---|---|
| L1 3-stage funnel | ✅ `shield/layer1_funnel.py` (`1A` Normalizer → `1B` Aho-Corasick 61 signatures → `1C` 22 bounded regex rules) |
| L2 intent extractor | ✅ `shield/intent_extractor.py` & `shield/layer2_providers.py` (Gemini / local Ollama / deterministic `HeuristicProvider`) |
| L3 policy gate | ✅ `shield/policy_gate.py` + `config/intent_catalog.yaml` (fail-closed, authority spoofing, multi-intent smuggling, RBAC, ABAC) |
| L4 origin gate | ✅ `app/provenance.py`: `unknown-tool`, `untrusted-origin`, `role-mismatch`, `wrong-principal`, `tainted-argument`, `needs-confirmation`, Rule of Two |
| Secure uploads | ✅ per-chunk scan before indexing, hidden-text detection, quarantine, per-visitor scoping |
| Output checks | ✅ canary, PII masking, link sanitising, citations, secret warning |
| Chat + missions | ✅ streaming live trace, 8 missions, two profiles |
| Recorded demos | ✅ `/demos` replays `dashboard/lib/demo-recordings.json` (from `scripts/record_demos.py`) |
| Public demo mode | ✅ 4 requests per visitor + network and daily caps, bring-your-own-key, scoped live feed |
| Deploy | ✅ root `Dockerfile` (one container, port 7860), `deploy/huggingface/` Space files |
| Scorecard | ✅ `attacks/run_attacks.py` updated for `none`, `layer1`, and `all3` (zero-judge) |

## Open

- Tool planning in `node_act` is rule-based. Next step: let a model plan behind the L4 gate.
- The vector index is in-memory (rebuilt from the knowledge base on start).
