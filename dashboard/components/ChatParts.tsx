"use client";
/** Chat message building blocks, shared by /chat (live) and /demos (recorded replays). */
import type React from "react";
import type { TurnEvent } from "@/lib/api";
import TurnProgress from "@/components/TurnProgress";
import { KavachMark, ShieldLayerMark } from "@/components/Brand";

export type Txn = {
  txn_id: string; direction: string; type: string; counterparty: string;
  amount_inr: number; status: string; date: string; dispute_ticket?: string;
};
export type Gate = { tool: string; origin: string; verdict: string; rule: string; reason: string; arg_origins?: Record<string, string> };
export type Msg = {
  role: "user" | "bot" | "upload" | "system";
  text: string;
  sources?: { id: string; title: string; heading: string }[];
  actions?: string[];
  tools?: string[];
  blocked?: boolean;
  confirm?: { token: string; summary: string; tool?: string; rule?: string; reason?: string } | null;
  confirmed?: string;
  redactions?: string[];
  intent?: string;
  shield?: any;
  timings?: Record<string, number>;
  model?: { provider: string; model: string };
  trace?: TurnEvent[];
  gate?: Gate[];
  upload?: UploadState;
};
export type UploadState = {
  filename: string; stage: string; pages?: number; hidden?: number[]; chunks: any[]; total?: number;
  scanning?: number; final?: any; error?: string;
};

export const TOOL_LABEL: Record<string, string> = {
  get_account_summary: "Checked your account",
  get_recent_transactions: "Looked up transactions",
  get_transaction: "Opened transaction",
  raise_dispute: "Raised dispute",
  block_upi: "Prepared UPI block",
  escalate_to_human: "Opened specialist ticket",
  admin_list_accounts: "Listed accounts (admin)",
  admin_unblock_upi: "Unblocked UPI (admin)",
  admin_security_summary: "Security summary (admin)",
};
export const STATUS_STYLE: Record<string, string> = {
  success: "text-[var(--pn-ok)] bg-[rgba(46,230,166,.1)]",
  failed: "text-[var(--pn-bad)] bg-[rgba(255,93,122,.12)]",
  pending: "text-[var(--pn-warn)] bg-[rgba(255,181,71,.12)]",
  reversed: "text-[#8fb7ff] bg-[rgba(143,183,255,.12)]",
};
export const LAYER_CHIP: Record<string, string> = {
  "L1-3": "text-[#5eead4] border-[#5eead4]/30", L4: "text-[#c4b5fd] border-[#c4b5fd]/35",
  "Rule of Two": "text-[#fcd34d] border-[#fcd34d]/30", Output: "text-[#93c5fd] border-[#93c5fd]/30",
  Tools: "text-[#86efac] border-[#86efac]/30",
};
export const inr = (n: number) => "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

/** Tiny safe markdown: **bold**, bullets, [cN] chips, line breaks. No HTML injection. */
export function RichText({ text, sources }: { text: string; sources?: Msg["sources"] }) {
  const renderInline = (s: string, key: string) =>
    s.split(/(\*\*[^*]+\*\*|\[c\d+\])/g).filter(Boolean).map((p, i) => {
      if (p.startsWith("**") && p.endsWith("**"))
        return <strong key={key + i} className="text-white font-semibold">{p.slice(2, -2)}</strong>;
      const m = p.match(/^\[c(\d+)\]$/);
      if (m) {
        const src = sources?.find((x) => x.id === `c${m[1]}`);
        return <span key={key + i} title={src ? `${src.title} › ${src.heading}` : ""}
          className="inline-flex items-center align-middle mx-0.5 px-1.5 h-[18px] rounded-md text-[10px] font-semibold bg-[rgba(94,234,212,.15)] text-[#99f6e4] cursor-help">{m[1]}</span>;
      }
      return <span key={key + i}>{p}</span>;
    });
  const out: React.ReactNode[] = [];
  let list: React.ReactNode[] = [];
  const flush = () => { if (list.length) out.push(<ul key={"ul" + out.length} className="my-1.5 space-y-1">{list}</ul>); list = []; };
  text.split(/\n/).forEach((ln, i) => {
    const b = ln.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (b) list.push(<li key={i} className="flex gap-2"><span className="mt-[9px] w-1.5 h-1.5 rounded-full bg-[var(--pn-accent-2)] shrink-0" /><span>{renderInline(b[1], "l" + i)}</span></li>);
    else { flush(); if (ln.trim()) out.push(<p key={i} className="my-1">{renderInline(ln.replace(/^#+\s*/, ""), "p" + i)}</p>); }
  });
  flush();
  return <>{out}</>;
}

/** One assistant reply: tools, masking, gate decisions, confirmation card, sources and the
 *  per-layer verdict dropdown. Shared by the live chat and the recorded-demo replays. */
export function BotMessage({ m, open, onToggle, onConfirm, onCancel }: {
  m: Msg; open: boolean; onToggle: () => void; onConfirm?: (token: string) => void; onCancel?: () => void;
}) {
  return (
    <div className="pn-fade-in self-start w-full flex gap-3">
      <KavachMark size={30} className="shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0 max-w-[92%]">
        {m.tools && m.tools.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">{Array.from(new Set(m.tools)).map((t) => (
            <span key={t} className="text-[11px] px-2 py-1 rounded-full bg-[rgba(0,212,200,.1)] text-[#7ff3ea] border border-[rgba(0,212,200,.25)]">⚡ {TOOL_LABEL[t] ?? t}</span>))}</div>
        )}
        {m.redactions && m.redactions.length > 0 && (
          <div className="mb-2 rounded-xl px-3 py-2 text-[12.5px] bg-[rgba(255,181,71,.1)] border border-[rgba(255,181,71,.3)] text-[#ffd49a]">
            🔐 I hid the {m.redactions.join(", ")} you typed — it never reached the AI or our logs.</div>
        )}
        <div className={`rounded-2xl rounded-tl-md px-4 py-3 text-[14.5px] leading-relaxed text-[#dfe4f5] break-words ${m.blocked ? "bg-[rgba(255,93,122,.08)] border border-[rgba(255,93,122,.35)]" : "pn-bubble-bot"}`}>
          {m.blocked && m.shield?.verdict === "block" && (
            <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--pn-bad)] mb-1">Blocked by ShieldLayer · {m.shield.layer}</div>)}
          <RichText text={m.text} sources={m.sources} />
        </div>

        {m.gate && m.gate.some((g) => g.verdict !== "allow") && <GatePanel gate={m.gate} />}
        {m.gate && m.gate.length > 0 && m.gate.every((g) => g.verdict === "allow") && (
          <div className="mt-1.5 text-[10.5px] font-mono text-[#c4b5fd]">L4 ✓ {m.gate.length} action(s) checked · requested by {m.gate[0].origin}</div>)}

        {m.actions?.map((a, j) => (
          <div key={j} className="mt-2 rounded-xl px-3 py-2 text-[13px] bg-[rgba(46,230,166,.08)] border border-[rgba(46,230,166,.3)] text-[#9ff5d4]">✓ {a}</div>))}

        {m.confirm && (
          <div className="mt-2 rounded-2xl p-3.5 bg-[rgba(252,211,77,.06)] border border-[rgba(252,211,77,.35)]">
            <div className="text-[13px] font-semibold text-white">Confirm action</div>
            <div className="text-[12.5px] text-[#dfe4f5] mt-0.5">{m.confirm.summary}</div>
            {m.confirm.rule === "rule-of-two" && <div className="text-[11.5px] text-[#fcd34d] mt-1">L4 Rule of Two: this chat read an uploaded file, so actions need your tap.</div>}
            {m.confirmed ? <div className="mt-2 text-[13px] text-[var(--pn-ok)]">✓ {m.confirmed}</div> : (
              <div className="mt-2.5 flex gap-2">
                <button onClick={() => onConfirm?.(m.confirm!.token)} disabled={!onConfirm} className={`px-3.5 py-1.5 rounded-lg text-[13px] font-semibold text-white hover:brightness-110 ${m.confirm.tool === "block_upi" ? "bg-[var(--pn-bad)]" : "bg-[#4f46e5]"}`}>
                  {m.confirm.tool === "block_upi" ? "Yes, block UPI now" : "Confirm"}</button>
                <button onClick={() => onCancel?.()} disabled={!onCancel} className="pn-chip px-3.5 py-1.5 rounded-lg text-[13px]">Not now</button>
              </div>)}
          </div>
        )}

        {m.sources && m.sources.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">{m.sources.map((s) => (
            <span key={s.id} className="text-[10.5px] px-2 py-0.5 rounded-md bg-white/5 text-[var(--pn-muted)] border border-[var(--pn-line)]">
              <b className="text-[#99f6e4]">{s.id.slice(1)}</b> {s.title}{s.heading ? ` › ${s.heading.split(">").pop()?.trim()}` : ""}</span>))}</div>
        )}

        {m.shield && (
          <button onClick={onToggle} aria-expanded={open}
            className="mt-1.5 inline-flex items-center gap-1.5 text-[11px] text-[var(--pn-muted)] hover:text-white">
            <ShieldLayerMark size={12} />
            <span className={m.shield.verdict === "block" ? "text-[var(--pn-bad)]" : "text-[var(--pn-ok)]"}>
              {m.shield.verdict === "block" ? `blocked at ${layerName(m.shield.layer)}` : "passed all checks"}</span>
            <span>· security check{m.timings ? ` · ${Math.round(Object.values(m.timings).reduce((a, b) => a + b, 0))}ms` : ""}</span>
            <span className="text-[13px] leading-none">{open ? "▴" : "▾"}</span>
          </button>)}
        {open && (
          <div className="mt-1 pn-glass rounded-xl p-3 space-y-3">
            <LayerVerdicts m={m} />
            {m.trace && m.trace.length > 0 && (
              <details>
                <summary className="cursor-pointer text-[11px] text-[var(--pn-muted)] hover:text-white">Full step-by-step trace</summary>
                <div className="mt-2"><TurnProgress events={m.trace} /></div>
              </details>)}
          </div>)}
      </div>
    </div>
  );
}

export const layerName = (l?: string) =>
  ({ layer1: "L1 deterministic funnel", regex: "L1 deterministic funnel", layer2: "L2 intent extractor", layer3: "L3 policy gate" } as Record<string, string>)[l ?? ""] ?? (l || "—");

type Row = { k: string; name: string; state: "allow" | "block" | "unsure" | "held" | "skip" | "unknown"; detail: string };

/** Which layer allowed, blocked or never saw this message — derived from the 3-layer pipeline verdicts. */
function layerRows(m: Msg): Row[] {
  const sh = m.shield ?? {};
  const layer: string = sh.layer;
  const block = sh.verdict === "block";
  const ruleId: string = sh.rule_id ?? "";
  const is1A = ruleId.startsWith("obfuscation_");
  const is1B = ruleId.startsWith("ac_");
  const is1C = (layer === "regex" || layer === "layer1") && !is1A && !is1B && block;
  const isL1Blocked = block && (layer === "regex" || layer === "layer1");
  const isL3Blocked = block && (layer === "layer3" || layer === "policy_gate");

  const rows: Row[] = [];
  if (layer === "unavailable" || !layer) {
    rows.push({ k: "L1–3", name: "Shield", state: "unknown", detail: sh.reason || "shield unavailable (chat fails open)" });
  } else {
    // Stage 1A: Canonicalization & De-obfuscation
    rows.push({
      k: "L1.A",
      name: "Canonicalizer",
      state: is1A ? "block" : "allow",
      detail: is1A ? `obfuscation: ${sh.reason || ruleId}` : "clean NFKC Unicode, zero-width & bidi clean",
    });
    // Stage 1B: Aho-Corasick Multi-Pattern Scan
    rows.push({
      k: "L1.B",
      name: "Aho-Corasick scan",
      state: is1A ? "skip" : is1B ? "block" : "allow",
      detail: is1B ? `matched signature ${ruleId} (${sh.owasp || "LLM01"})` : is1A ? "not reached" : "61 static signatures checked · clean",
    });
    // Stage 1C: Targeted ReDoS-Safe Regex
    rows.push({
      k: "L1.C",
      name: "Targeted regex",
      state: (is1A || is1B) ? "skip" : is1C ? "block" : "allow",
      detail: is1C ? `matched rule ${ruleId} (${sh.owasp || "LLM01"})` : (is1A || is1B) ? "not reached" : "22 bounded regex rules · no rule matched",
    });

    // Layer 2: Quarantined Intent Extractor & Neutralizer
    const ext = sh.extraction;
    const extSummary = ext?.intents?.length
      ? `extracted [${ext.intents.map((x: any) => x.intent).join(", ")}] · ${ext.intents[0]?.neutral_summary || "neutralized"} (${ext.provider_used || "quarantine"})`
      : "schema-enforced JSON extracted & neutralized (zero-tool sandbox)";
    rows.push({
      k: "L2",
      name: "Intent extractor",
      state: isL1Blocked ? "skip" : "allow",
      detail: isL1Blocked ? "not reached (stopped at L1)" : extSummary,
    });

    // Layer 3: Deterministic Policy & Symbolic Gate
    const pol = sh.policy;
    const l3Detail = isL3Blocked
      ? `blocked [${sh.rule_id || "POL"}] ${sh.reason || "policy violation"}`
      : pol?.reason || "100% deterministic RBAC/ABAC and authority invariants verified";
    rows.push({
      k: "L3",
      name: "Policy gate",
      state: isL1Blocked ? "skip" : isL3Blocked ? "block" : "allow",
      detail: isL1Blocked ? "not reached" : l3Detail,
    });
  }
  const gate = m.gate ?? [];
  const denied = gate.filter((g) => g.verdict === "deny"), held = gate.filter((g) => g.verdict === "confirm");
  if (gate.length > 0) {
    rows.push(block ? { k: "Gate", name: "Pre-tool gate", state: "skip", detail: "not reached (message stopped earlier)" }
      : denied.length ? { k: "Gate", name: "Pre-tool gate", state: "block", detail: denied.map((g) => `${g.tool} from ${g.origin}: ${g.reason}`).join(" · ") }
      : held.length ? { k: "Gate", name: "Pre-tool gate", state: "held", detail: held.map((g) => `${g.tool}: ${g.reason}`).join(" · ") }
      : { k: "Gate", name: "Pre-tool gate", state: "allow", detail: `${gate.length} action(s), all requested by ${gate[0].origin}` });
  }
  return rows;
}

const STATE_STYLE: Record<Row["state"], [string, string]> = {
  allow: ["ALLOWED", "bg-[rgba(46,230,166,.12)] text-[var(--pn-ok)]"],
  block: ["BLOCKED", "bg-[rgba(255,93,122,.15)] text-[var(--pn-bad)]"],
  unsure: ["UNSURE", "bg-[rgba(252,211,77,.14)] text-[#fcd34d]"],
  held: ["NEEDS YOU", "bg-[rgba(252,211,77,.14)] text-[#fcd34d]"],
  skip: ["NOT REACHED", "bg-white/5 text-[var(--pn-muted)]"],
  unknown: ["UNKNOWN", "bg-white/5 text-[var(--pn-muted)]"],
};

export function LayerVerdicts({ m }: { m: Msg }) {
  const rows = layerRows(m);
  return (
    <ul className="space-y-1.5">
      {rows.map((r) => {
        const [label, cls] = STATE_STYLE[r.state];
        return (
          <li key={r.k} className={`grid grid-cols-[34px_92px_1fr] items-start gap-2 text-[12px] ${r.state === "skip" ? "opacity-60" : ""}`}>
            <span className="font-mono text-[11px] text-[#5eead4] pt-[2px]">{r.k}</span>
            <span className={`font-mono text-[10px] text-center rounded px-1.5 py-[2px] ${cls}`}>{label}</span>
            <span><b className="font-medium text-[#dfe4f5]">{r.name}</b> <span className="text-[var(--pn-muted)]">· {r.detail}</span></span>
          </li>
        );
      })}
      {(m.redactions?.length ?? 0) > 0 && (
        <li className="grid grid-cols-[34px_92px_1fr] gap-2 text-[12px]"><span className="font-mono text-[11px] text-[#5eead4]">IN</span>
          <span className="font-mono text-[10px] text-center rounded px-1.5 py-[2px] bg-[rgba(252,211,77,.14)] text-[#fcd34d]">MASKED</span>
          <span className="text-[var(--pn-muted)]">hid {m.redactions!.join(", ")} before the model saw it</span></li>)}
    </ul>
  );
}

export function GatePanel({ gate }: { gate: Gate[] }) {
  return (
    <div className="mt-2 rounded-xl border border-[#c4b5fd]/30 bg-[#c4b5fd]/[.05] p-3">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[.14em] text-[#c4b5fd] mb-2">
        <span className="font-mono">L4</span> Origin gate · who asked for each action
      </div>
      <ul className="space-y-1.5">
        {gate.map((g, k) => (
          <li key={k} className="text-[12.5px]">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className={`font-mono text-[10.5px] px-1.5 py-[1px] rounded ${g.verdict === "deny" ? "bg-[rgba(255,93,122,.15)] text-[var(--pn-bad)]" : g.verdict === "confirm" ? "bg-[rgba(252,211,77,.15)] text-[#fcd34d]" : "bg-[rgba(46,230,166,.12)] text-[var(--pn-ok)]"}`}>
                {g.verdict === "deny" ? "REFUSED" : g.verdict === "confirm" ? "NEEDS YOU" : "ALLOWED"}</span>
              <span className="font-mono text-[12px] text-white">{g.tool}</span>
              <span className="text-[var(--pn-muted)]">requested by</span>
              <span className="font-mono text-[11px] px-1.5 rounded border border-[var(--pn-line)]">{g.origin}</span>
              {g.arg_origins && Object.entries(g.arg_origins).map(([k2, v]) => (
                <span key={k2} className="font-mono text-[11px] text-[var(--pn-muted)]">{k2} ← <b className={v === "user" || v === "admin" || v === "database" ? "text-[var(--pn-ok)]" : "text-[var(--pn-bad)]"}>{v}</b></span>))}
            </div>
            <div className="text-[11.5px] text-[var(--pn-muted)] mt-0.5">{g.reason}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function UploadCard({ u }: { u: UploadState }) {
  const f = u.final;
  const blocked = u.chunks.filter((c) => c.verdict === "block").length;
  return (
    <div className="pn-fade-in self-end w-full max-w-[560px]">
      <div className="rounded-2xl border border-[var(--pn-line)] bg-white/[.03] p-3.5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-11 rounded-lg grid place-items-center text-[10px] font-bold bg-[rgba(255,93,122,.15)] text-[#ffb4c1] border border-[rgba(255,93,122,.3)]">{u.filename.split(".").pop()?.toUpperCase()}</div>
          <div className="flex-1 min-w-0">
            <div className="text-[13.5px] font-medium truncate">{u.filename}</div>
            <div className="text-[11.5px] text-[var(--pn-muted)]">
              {u.error ? <span className="text-[var(--pn-bad)]">{u.error}</span>
                : f ? `${f.chunks_indexed} of ${f.chunks_total} sections indexed · ${f.chunks_quarantined} quarantined`
                : u.pages ? `${u.pages} page(s) · ${u.total} section(s) · scanning ${u.chunks.length + (u.scanning !== undefined ? 1 : 0)}/${u.total}`
                : "uploading and parsing…"}
            </div>
          </div>
          {!f && !u.error && <span className="pn-step-spin" />}
          {f && <span className={`text-[10.5px] font-mono px-2 py-1 rounded-md ${f.chunks_quarantined ? "bg-[rgba(255,93,122,.15)] text-[var(--pn-bad)]" : "bg-[rgba(46,230,166,.12)] text-[var(--pn-ok)]"}`}>{f.status.toUpperCase()}</span>}
        </div>
        {(u.hidden?.length ?? 0) > 0 && <div className="mt-2 text-[11.5px] text-[#fcd34d]">⚠ Hidden text found on page {u.hidden!.join(", ")} (white, tiny or off-page)</div>}
        {u.chunks.length > 0 && (
          <ul className="mt-2.5 space-y-1 border-t border-[var(--pn-line)] pt-2.5">
            {u.chunks.map((c) => (
              <li key={c.i} className="flex items-start gap-2 text-[11.5px]">
                <span className={`font-mono shrink-0 w-[58px] ${c.verdict === "block" ? "text-[var(--pn-bad)]" : "text-[var(--pn-ok)]"}`}>{c.verdict === "block" ? "✕ BLOCK" : "✓ CLEAN"}</span>
                <span className="font-mono shrink-0 text-[var(--pn-muted)] w-[78px]">{c.layer}{c.score != null ? ` ${Number(c.score).toFixed(2)}` : ""}</span>
                <span className="text-[#c9d0e6] truncate">{c.preview}</span>
              </li>
            ))}
            {u.scanning !== undefined && <li className="flex items-center gap-2 text-[11.5px] text-[var(--pn-muted)]"><span className="pn-step-spin" /> scanning section {u.scanning + 1} with L1 → L2 → L3…</li>}
          </ul>
        )}
        {f && (
          <div className="mt-2.5 text-[11.5px] text-[var(--pn-muted)] leading-relaxed">
            {blocked > 0 ? "Flagged sections went to quarantine and will never be used to answer you. " : "Every section passed, so Kavi can now answer questions about this file. "}
            <span className="text-[#fcd34d]">Rule of Two is now on for this chat: any action needs your confirmation.</span>
          </div>
        )}
      </div>
    </div>
  );
}

/** Fold one upload stream event into the card state (live upload and replay). */
export function applyUploadEvent(u: UploadState, ev: any) {
  u.stage = ev.stage ?? ev.type;
  if (ev.stage === "parse") { u.pages = ev.pages; u.hidden = ev.hidden_pages; u.total = ev.chunks; }
  if (ev.stage === "scan_start") u.scanning = ev.i;
  if (ev.stage === "scan") { u.chunks.push(ev); u.scanning = undefined; }
  if (ev.type === "final") u.final = ev;
}

/** Map a chat API response (live or recorded) to a bot message. */
export function botFromResponse(r: any, trace: TurnEvent[]): Msg {
  return {
    role: "bot", text: r.reply, sources: r.sources, actions: r.actions, blocked: r.blocked,
    confirm: r.confirm, redactions: r.redactions, intent: r.intent, shield: r.shield,
    timings: r.timings, tools: r.tools, model: r.model, trace, gate: r.gate,
  };
}
