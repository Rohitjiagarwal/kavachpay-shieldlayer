"""Replay the attack library through the 3-Layer Zero-Judge Shield funnel and print the scorecard.

Usage:
  python -m attacks.run_attacks                 # detection, all setups
  python -m attacks.run_attacks --out attacks/results
"""
from __future__ import annotations

import os as _os

_os.environ.setdefault("LAYER2_PROVIDER", "heuristic")  # automated batches never spend API quota

import argparse
import datetime as dt
import json
from pathlib import Path

import yaml

from app.scanner import ScanClient
from shared.schemas import Layer, ScanItem, Source, Verdict

HERE = Path(__file__).resolve().parent
LIB = HERE / "library"
RESULTS = HERE / "results"

SETUPS = {
    "none": [],
    "layer1": [Layer.layer1],
    "all3": [Layer.layer1, Layer.layer2, Layer.layer3],
}
SETUP_LABEL = {
    "none": "No guard",
    "layer1": "L1 Deterministic Funnel",
    "all3": "All 3 layers (Zero-Judge)",
}


def load_library() -> list[dict]:
    cases = []
    for path in sorted(LIB.glob("*.yaml")):
        docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        for d in docs:
            if not d:
                continue
            d["_file"] = path.name
            cases.append(d)
    return cases


def run_detection(cases: list[dict], scanner: ScanClient) -> dict:
    attacks = [c for c in cases if c.get("expected", "block") == "block"]
    safes = [c for c in cases if c.get("expected") == "allow"]

    report: dict = {"setups": {}, "n_attacks": len(attacks), "n_safe": len(safes)}
    per_owasp: dict = {}

    for setup, layers in SETUPS.items():
        a_items = [ScanItem(id=c["id"], text=c["text"],
                            source=Source(c.get("source_kind", "user"))) for c in attacks]
        s_items = [ScanItem(id=c["id"], text=c["text"],
                            source=Source(c.get("source_kind", "user"))) for c in safes]
        if setup == "none":
            a_res = [_allow(it) for it in a_items]
            s_res = [_allow(it) for it in s_items]
        else:
            a_res = scanner.scan(a_items, layers=layers)
            s_res = scanner.scan(s_items, layers=layers)

        lat = sorted(d.latency_ms for d in a_res + s_res)
        blocked_attacks = sum(1 for d in a_res if d.verdict == Verdict.block)
        blocked_safe = sum(1 for d in s_res if d.verdict == Verdict.block)
        l3_hits = sum(1 for d in a_res + s_res if d.layer == Layer.layer3 and d.verdict == Verdict.block)
        n = len(a_res) + len(s_res)

        report["setups"][setup] = {
            "label": SETUP_LABEL[setup],
            "attacks_blocked_pct": round(100 * blocked_attacks / max(1, len(attacks)), 1),
            "safe_blocked_pct": round(100 * blocked_safe / max(1, len(safes)), 1),
            "p50_ms": round(_pct(lat, 50), 2),
            "p95_ms": round(_pct(lat, 95), 2),
            "l3_block_share_pct": round(100 * l3_hits / max(1, n), 1),
        }

        if setup == "all3":
            for c, d in zip(attacks, a_res):
                owasp = c.get("owasp", ["NONE"])[0] if isinstance(c.get("owasp"), list) else c.get("owasp", "NONE")
                per_owasp.setdefault(owasp, {"total": 0, "blocked": 0})
                per_owasp[owasp]["total"] += 1
                per_owasp[owasp]["blocked"] += 1 if d.verdict == Verdict.block else 0

    report["per_owasp"] = {
        k: round(100 * v["blocked"] / v["total"], 1) for k, v in sorted(per_owasp.items())
    }
    report["scanner_mode"] = scanner.mode
    report["pipeline"] = "3-layer-zero-judge"
    try:
        from shield.config import layer2_provider_label

        report["layer2_provider"] = layer2_provider_label()
    except Exception:  # noqa: BLE001
        report["layer2_provider"] = "unknown"
    return report


def _allow(item: ScanItem):
    from shared.schemas import Decision

    return Decision(verdict=Verdict.allow, layer=Layer.none, latency_ms=0.0)


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = int(round((p / 100) * (len(sorted_vals) - 1)))
    return sorted_vals[k]


def print_scorecard(report: dict) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        t = Table(title=f"ShieldLayer scorecard — {report['n_attacks']} attacks, "
                        f"{report['n_safe']} safe  "
                        f"(pipeline: {report.get('pipeline')}, "
                        f"L2: {report.get('layer2_provider')})")
        for col in ["Setup", "Attacks blocked", "Safe wrongly blocked", "p95 ms", "L3 block share"]:
            t.add_column(col)
        for setup in SETUPS:
            r = report["setups"][setup]
            t.add_row(r["label"], f"{r['attacks_blocked_pct']}%", f"{r['safe_blocked_pct']}%",
                      f"{r['p95_ms']}", f"{r['l3_block_share_pct']}%")
        console.print(t)
        if report.get("per_owasp"):
            t2 = Table(title="All-3-layers: attacks blocked per OWASP id")
            t2.add_column("OWASP")
            t2.add_column("% blocked")
            for k, v in report["per_owasp"].items():
                t2.add_row(k, f"{v}%")
            console.print(t2)
    except ImportError:
        print(json.dumps(report, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--baseline", action="store_true", help="also write baseline.json")
    args = ap.parse_args()

    cases = load_library()
    scanner = ScanClient()
    report = run_detection(cases, scanner)
    report["generated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    print_scorecard(report)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().isoformat()
    (out / f"{date}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / f"{date}.md").write_text(_markdown(report), encoding="utf-8")
    (out / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.baseline:
        (out / "baseline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out / (date + '.json')}")


def _markdown(report: dict) -> str:
    lines = [f"# ShieldLayer scorecard ({report['generated_at']})", "",
             f"{report['n_attacks']} attacks, {report['n_safe']} safe messages. "
             f"Scanner: {report['scanner_mode']}; pipeline: {report.get('pipeline')}; "
             f"L2 provider: {report.get('layer2_provider')}.", "",
             "| Setup | Attacks blocked | Safe wrongly blocked | p95 ms | L3 block share |",
             "|---|---|---|---|---|"]
    for setup in SETUPS:
        r = report["setups"][setup]
        lines.append(f"| {r['label']} | {r['attacks_blocked_pct']}% | {r['safe_blocked_pct']}% "
                     f"| {r['p95_ms']} | {r['l3_block_share_pct']}% |")
    if report.get("per_owasp"):
        lines += ["", "## All 3 layers — blocked per OWASP id", "", "| OWASP | % blocked |", "|---|---|"]
        for k, v in report["per_owasp"].items():
            lines.append(f"| {k} | {v}% |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
