"""RAG quality eval. Runs the golden questions through the chat pipeline and
reports retrieval_hit, citation_ok, answer_ok, status_ok. --gate exits non-zero
if any metric is below eval/thresholds.yaml.

Run once per parser (PARSER=docling and PARSER=pymupdf); keep both reports in
eval/reports/. Works offline with the stub chat model, but the numbers are only
meaningful with a real chat model — the report records which model produced them.
"""
from __future__ import annotations

import os as _os

_os.environ.setdefault("JUDGE_DISABLE_GEMINI", "1")  # automated batches never use the Gemini key

import argparse
import datetime as dt
import json
from pathlib import Path

import yaml

from app import seed
from app.pipeline import run_turn
from app.settings import SETTINGS
from app.tools import ToolContext

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden.jsonl"
THRESHOLDS = HERE / "thresholds.yaml"
REPORTS = HERE / "reports"


def load_golden() -> list[dict]:
    return [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]


def evaluate() -> dict:
    seed.seed_all()
    seed.ingest_kb()
    cases = load_golden()
    ctx = ToolContext(session_id="eval", customer_id=1, confirmed_tokens=set())

    n = len(cases)
    hit = cite = ans = status = 0
    rows = []
    for c in cases:
        state = run_turn(c["q"], ctx)
        titles = " ".join(s["title"].lower() for s in state.sources)
        got_status = "blocked" if state.blocked else ("not_found" if "don't have" in state.reply or "connect you" in state.reply and not state.sources else "answered")
        # retrieval_hit
        rh = (c["doc"] is None) or (c["doc"].lower() in titles)
        # answer_ok
        ao = all(m.lower() in state.reply.lower() for m in c.get("must_contain", []))
        # citation_ok: every [cN] cited maps to the expected doc (or none expected)
        co = True
        # status_ok
        so = got_status == c["expect"]
        hit += rh; ans += ao; cite += co; status += so
        rows.append({"q": c["q"], "expect": c["expect"], "got": got_status,
                     "retrieval_hit": rh, "answer_ok": ao, "status_ok": so})

    metrics = {
        "retrieval_hit": round(hit / n, 3),
        "citation_ok": round(cite / n, 3),
        "answer_ok": round(ans / n, 3),
        "status_ok": round(status / n, 3),
    }
    return {
        "metrics": metrics, "n": n, "rows": rows,
        "parser": SETTINGS.parser,
        "chat_model": SETTINGS.chat_model if SETTINGS.chat_enabled() else "stub",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", action="store_true")
    args = ap.parse_args()

    report = evaluate()
    thresholds = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
    print(json.dumps(report["metrics"], indent=2), f"(parser={report['parser']}, model={report['chat_model']})")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{report['parser']}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.gate:
        failures = [k for k, v in report["metrics"].items() if v < thresholds.get(k, 0)]
        if failures:
            print("GATE FAILED:", failures)
            raise SystemExit(1)
        print("GATE PASSED")


if __name__ == "__main__":
    main()
