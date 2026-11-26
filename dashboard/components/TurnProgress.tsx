"use client";
import { useEffect, useState } from "react";
import type { TurnEvent } from "@/lib/api";

type Sub = { id: string; status: string; detail?: string };
type Row = {
  id: string; label: string; status: string; detail?: string; ms?: number; t?: number; subs: Sub[];
};

const LAYER_NAME: Record<string, string> = {
  regex: "L1 · Deterministic funnel",
  stage_1a: "L1.A · Canonicalizer & De-obfuscation",
  stage_1b: "L1.B · Aho-Corasick pattern scan",
  stage_1c: "L1.C · Targeted regex engine",
  layer2: "L2 · Quarantined intent extractor",
  layer3: "L3 · Deterministic policy gate",
  classifier: "L2 · Quarantined intent extractor",
  judge: "L3 · Deterministic policy gate",
};
const TOOL_NAME: Record<string, string> = {
  get_account_summary: "Account summary",
  get_recent_transactions: "Recent transactions",
  get_transaction: "Transaction lookup",
  raise_dispute: "Raise dispute",
  block_upi: "Block UPI (needs your confirmation)",
  escalate_to_human: "Specialist ticket",
  admin_list_accounts: "Admin: list accounts",
  admin_unblock_upi: "Admin: unblock UPI",
  admin_security_summary: "Admin: security summary",
};

/** Fold the raw event stream into ordered timeline rows. */
export function buildRows(events: TurnEvent[]): Row[] {
  const rows: Row[] = [];
  const byId = new Map<string, Row>();
  const get = (id: string, label = id) => {
    let r = byId.get(id);
    if (!r) { r = { id, label, status: "start", subs: [] }; byId.set(id, r); rows.push(r); }
    return r;
  };
  for (const e of events) {
    if (e.type === "step" && e.id) {
      const r = get(e.id, e.label);
      r.label = e.label || r.label;
      r.status = e.status || r.status;
      if (e.detail !== undefined) r.detail = e.detail;
      if (e.ms !== undefined) r.ms = e.ms;
      if (e.status === "start") r.t = e.t;
    } else if (e.type === "layer" && e.id) {
      const r = get("shield", "Scanning the message with ShieldLayer");
      const s = r.subs.find((x) => x.id === e.id);
      if (s) { s.status = e.status || s.status; s.detail = e.detail; }
      else r.subs.push({ id: e.id, status: e.status || "start", detail: e.detail });
    } else if (e.type === "tool" && e.id) {
      const r = get("act", "Running account tools");
      const s = [...r.subs].reverse().find((x) => x.id === e.id && x.status === "start");
      if (s && e.status !== "start") { s.status = e.status || "done"; s.detail = e.detail; }
      else r.subs.push({ id: e.id, status: e.status || "start", detail: e.detail });
    } else if (e.type === "gate" && e.id) {
      const parent = byId.get("origin_gate")?.status === "start" ? "origin_gate" : "act";
      const r = get(parent, parent === "act" ? "Planning and running tools" : "L4 Origin gate");
      const st = e.status === "allow" ? "done" : e.status === "deny" ? "block" : "confirm";
      r.subs.push({ id: `gate:${e.id}`, status: st, detail: `${e.origin} → ${e.id}: ${e.detail}` });
    } else if (e.type === "model") {
      const r = get("generate", "Writing the reply");
      if (e.phase === "start") r.detail = `${e.detail} is reading the prompt…`;
      else if (e.phase === "prompt") r.detail = (r.detail || "").replace(/ is .*$/, "") + " is reading the prompt…";
      else if (e.phase === "writing") {
        const who = (r.detail || "").split(" ")[0];
        r.detail = `${who} is writing · ${e.tokens} tokens`;
      }
    }
  }
  return rows;
}

function Icon({ status }: { status: string }) {
  if (status === "start") return <span className="pn-step-spin shrink-0" aria-label="running" />;
  if (status === "skip") return <span className="w-[13px] text-center text-[var(--pn-muted)] shrink-0">–</span>;
  if (status === "block" || status === "denied")
    return <span className="w-[13px] text-center text-[var(--pn-bad)] shrink-0 font-bold">✕</span>;
  if (status === "warn" || status === "unsure" || status === "confirm")
    return <span className="w-[13px] text-center text-[var(--pn-warn)] shrink-0 font-bold">!</span>;
  return <span className="w-[13px] text-center text-[var(--pn-ok)] shrink-0">✓</span>;
}

/** Live (or replayed) timeline of what the pipeline is really doing. */
export default function TurnProgress({ events, running, startedAt }:
  { events: TurnEvent[]; running?: boolean; startedAt?: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [running]);
  const rows = buildRows(events);
  const elapsed = startedAt ? (now - startedAt) / 1000 : 0;

  return (
    <div className="text-[12.5px]">
      {running && (
        <div className="flex items-center justify-between mb-2 text-[11px] uppercase tracking-[.14em] text-[var(--pn-muted)]">
          <span>Working on it</span>
          <span className="font-mono normal-case tracking-normal">{elapsed.toFixed(1)}s</span>
        </div>
      )}
      <ol className="space-y-1.5">
        {rows.map((r) => {
          const live = running && r.status === "start";
          const sinceStart = live && r.t !== undefined && startedAt ? Math.max(0, elapsed - r.t / 1000) : null;
          return (
            <li key={r.id} className={r.status === "skip" ? "opacity-45" : ""}>
              <div className="flex items-center gap-2.5">
                <Icon status={r.status} />
                <span className={`${live ? "text-white" : "text-[#cdd4ea]"}`}>{r.label}</span>
                <span className="flex-1" />
                <span className="font-mono text-[10.5px] text-[var(--pn-muted)] tabular-nums">
                  {r.ms !== undefined ? `${r.ms < 10 ? r.ms.toFixed(1) : Math.round(r.ms)}ms`
                    : sinceStart !== null ? `${sinceStart.toFixed(1)}s` : ""}
                </span>
              </div>
              {r.detail && <div className="ml-[23px] text-[11.5px] text-[var(--pn-muted)] break-words">{r.detail}</div>}
              {r.subs.length > 0 && (
                <ul className="ml-[23px] mt-1 space-y-1 border-l border-[var(--pn-line)] pl-3">
                  {r.subs
                    .filter((s) => s.id !== "regex" || !r.subs.some((x) => x.id.startsWith("stage_1")))
                    .map((s, i) => (
                    <li key={s.id + i} className="flex items-start gap-2 text-[11.5px]">
                      <span className="mt-[2px]"><Icon status={s.status === "pass" ? "done" : s.status} /></span>
                      <span className={`shrink-0 ${
                        s.id.startsWith("stage_")
                          ? "text-[#5eead4] font-mono text-[11.5px] font-semibold"
                          : s.id === "layer2" || s.id === "classifier"
                          ? "text-[#818cf8] font-mono text-[11.5px] font-semibold"
                          : s.id === "layer3" || s.id === "judge"
                          ? "text-[#a78bfa] font-mono text-[11.5px] font-semibold"
                          : s.id.startsWith("gate:")
                          ? "text-[#5eead4] font-mono text-[11px]"
                          : "text-[#cdd4ea]"
                      }`}>
                        {s.id.startsWith("gate:") ? "Policy gate" : LAYER_NAME[s.id] ?? TOOL_NAME[s.id] ?? s.id}
                      </span>
                      {s.detail && <span className="text-[var(--pn-muted)] min-w-0 break-words">· {s.detail}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
        {running && rows.length === 0 && (
          <li className="flex items-center gap-2.5"><span className="pn-step-spin" /><span>Sending your message…</span></li>
        )}
      </ol>
    </div>
  );
}
