"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Shell from "@/components/Shell";
import { LayerTag, Panel, VerdictBadge } from "@/components/VerdictBadge";
import { api } from "@/lib/api";
import { isAgent, timeAgo, tsOf, useFeed, type FeedItem } from "@/lib/useFeed";

const OWASP_NAME: Record<string, string> = {
  LLM01: "Prompt injection", LLM02: "Sensitive info disclosure", LLM05: "Improper output handling",
  LLM06: "Excessive agency", LLM07: "System prompt leakage", LLM08: "Vector/embedding weakness",
  LLM09: "Misinformation",
};
const TOOL_POLICY: Record<string, string> = {
  get_account_summary: "read · own account only",
  get_recent_transactions: "read · own account only",
  get_transaction: "read · id must come from you",
  raise_dispute: "write · id from you or your records",
  block_upi: "write · user must confirm",
  escalate_to_human: "write · rate-limited",
  admin_list_accounts: "admin · admin session only",
  admin_unblock_upi: "admin · admin session only",
  admin_security_summary: "admin · admin session only",
};

export default function Overview() {
  const [stats, setStats] = useState<any>(null);
  const [info, setInfo] = useState<any>(null);
  const [quarantined, setQuarantined] = useState<number | null>(null);
  const { items, connected } = useFeed(300);

  useEffect(() => {
    const pull = () => api.stats().then(setStats).catch(() => {});
    pull();
    api.shieldInfo().then(setInfo).catch(() => {});
    api.quarantine().then((r) => setQuarantined(r.length)).catch(() => {});
    const t = setInterval(pull, 3000);
    return () => clearInterval(t);
  }, []);

  const agent = useMemo(() => {
    const tools: Record<string, { calls: number; denied: number; confirm: number }> = {};
    let turns = 0, blockedTurns = 0, guard = 0, gateChecks = 0, gateDenied = 0, gateHeld = 0;
    const byOrigin: Record<string, number> = {};
    for (const x of items.filter(isAgent)) {
      if (x.event === "gate") {
        gateChecks++;
        const t = (tools[x.tool] ??= { calls: 0, denied: 0, confirm: 0 });
        if (x.status === "deny") { gateDenied++; t.denied++; byOrigin[x.origin] = (byOrigin[x.origin] ?? 0) + 1; }
        if (x.status === "confirm") { gateHeld++; t.confirm++; }
      } else if (x.event === "tool_call") {
        const t = (tools[x.tool] ??= { calls: 0, denied: 0, confirm: 0 });
        t.calls++;
      } else if (x.event === "turn") { turns++; if (x.blocked) blockedTurns++; }
      else if (x.event === "output_guard") guard++;
    }
    return { tools, turns, blockedTurns, guard, gateChecks, gateDenied, gateHeld, byOrigin };
  }, [items]);

  const checked = stats?.checked ?? 0;
  const blocked = stats?.blocked ?? 0;
  const byLayer = stats?.by_layer ?? {};
  const l1N = (byLayer.layer1 ?? 0) + (byLayer.regex ?? 0);
  const l2N = (byLayer.layer2 ?? 0) + (byLayer.classifier ?? 0);
  const l3N = (byLayer.layer3 ?? 0) + (byLayer.judge ?? 0);
  const toL2 = Math.max(0, checked - l1N);

  return (
    <Shell title="Overview" subtitle="Layers 1-3 scan every message, document chunk and tool result before a model sees it. Layer 4 checks where every agent action came from before it runs.">
      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-4">
        <Kpi label="Decisions" value={checked} hint="all-time funnel verdicts" />
        <Kpi label="Blocked" value={blocked} hint={checked ? `${((blocked / checked) * 100).toFixed(1)}% block rate` : "—"} accent="var(--block)" />
        <Kpi label="L3 Policy blocks" value={stats?.blocked_layer3 ?? stats?.blocked_judge ?? 0} hint="RBAC / ABAC / authority" accent="var(--l3)" />
        <Kpi label="Quarantined" value={quarantined ?? "—"} hint="poisoned doc chunks held" accent="var(--warn)" />
        <Kpi label="Agent turns" value={agent.turns} hint={`${agent.blockedTurns} stopped · last 200 events`} accent="var(--agent)" />
        <Kpi label="Output guard" value={agent.guard} hint="replies fixed before send" accent="var(--ok)" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Funnel */}
        <Panel title="Detection funnel" right={<span className="text-muted text-[11px]">where each verdict was made</span>} className="xl:col-span-2">
          <div className="space-y-3">
            <FunnelRow name="L1 · Deterministic Funnel (1A-1C)" color="var(--l1)" entered={checked} decided={l1N}
              blocked={stats?.blocked_layer1 ?? stats?.blocked_regex ?? 0} total={checked} note="< 2 ms · 1A Normalizer · 1B Aho-Corasick · 1C Regex" />
            <FunnelRow name="L2 · Quarantined Intent Extractor" color="var(--l2)" entered={toL2} decided={l2N}
              blocked={stats?.blocked_layer2 ?? stats?.blocked_classifier ?? 0} total={checked}
              note="Schema-enforced JSON · zero-tool sandbox" />
            <FunnelRow name="L3 · Deterministic Policy Gate" color="var(--l3)" entered={toL2} decided={l3N}
              blocked={stats?.blocked_layer3 ?? stats?.blocked_judge ?? 0} total={checked} note="100% deterministic RBAC/ABAC & authority invariants" />
          </div>
          <div className="mt-4 rounded-lg border border-[#c4b5fd]/30 bg-[#c4b5fd]/[.05] p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-[12.5px]">
              <span className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-sm bg-[#c4b5fd]" />Pre-tool Policy Gate <span className="text-muted text-[11px]">checks every action and intent</span></span>
              <span className="font-mono text-[11.5px]">{agent.gateChecks} checked · <span className="text-warn">{agent.gateHeld} held</span> · <span className="text-block">{agent.gateDenied} refused</span></span>
            </div>
            <div className="mt-2 flex flex-wrap gap-2 text-[11px] font-mono">
              {Object.keys(agent.byOrigin).length === 0 && <span className="text-muted">no refusals yet: try missions in the chat</span>}
              {Object.entries(agent.byOrigin).map(([o, n]) => <span key={o} className="rounded border border-line px-2 py-0.5">refused from <b className="text-[#c4b5fd]">{o}</b>: {n}</span>)}
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-line grid grid-cols-3 gap-3 text-[12px]">
            {(["user", "document", "tool"] as const).map((s) => {
              const v = stats?.by_source?.[s] ?? { allow: 0, block: 0 };
              const n = (v.allow ?? 0) + (v.block ?? 0);
              return (
                <div key={s}>
                  <div className="flex justify-between text-muted"><span className="capitalize">{s === "user" ? "chat messages" : s === "document" ? "doc chunks" : "tool output"}</span><span className="font-mono text-ink">{n}</span></div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-line overflow-hidden flex gap-[2px]">
                    {n > 0 && <div className="bg-ok h-full rounded-l-full" style={{ width: `${(v.allow / n) * 100}%` }} title={`${v.allow} allowed`} />}
                    {n > 0 && v.block > 0 && <div className="bg-block h-full rounded-r-full" style={{ width: `${(v.block / n) * 100}%` }} title={`${v.block} blocked`} />}
                  </div>
                  <div className="mt-1 text-[10.5px] text-muted font-mono">{v.allow ?? 0} allow · {v.block ?? 0} block</div>
                </div>
              );
            })}
          </div>
        </Panel>

        {/* Posture */}
        <Panel title="Guard posture" right={<span className="text-muted text-[11px] font-mono">{info?.scanner_mode ?? "in-process"}</span>}>
          <dl className="text-[12.5px] space-y-2">
            <Row k="Pipeline" v="3-Layer Zero-Judge" mono />
            <Row k="Layer 1" v="3-Stage Funnel (< 2ms)" />
            <Row k="Layer 2" v={info?.layer2 ?? "Quarantined Extractor"} />
            <Row k="Layer 3" v="Deterministic Policy Gate" />
            <Row k="Fail mode" v={info?.fail_modes?.chat ? `chat ${info.fail_modes.chat} · docs ${info.fail_modes.document}` : "open"} />
            <Row k="Verdict cache" v={info?.cache ? `${info.cache.hits} hits · ${info.cache.misses} misses` : "active"} mono />
          </dl>
          <div className="mt-4 rounded-lg border border-[#818cf8]/20 bg-[#818cf8]/[.04] p-2.5 text-[11px] text-[var(--pn-muted)]">
            <span className="font-semibold text-[#818cf8]">Zero-Judge Architecture:</span> No probabilistic classifier scores, no borderline LLM-as-a-judge prompts. 100% deterministic invariants.
          </div>
        </Panel>

        {/* Agent tools */}
        <Panel title="Agent tool activity" right={<span className="text-muted text-[11px]">tools run in code, never by the model</span>} bodyClass="p-0">
          <table className="w-full text-[12.5px]">
            <thead className="text-[10.5px] uppercase tracking-[.12em] text-muted">
              <tr className="border-b border-line"><th className="text-left font-medium px-4 py-2">Tool</th><th className="text-right font-medium px-2">Calls</th><th className="text-right font-medium px-4">L4 held / refused</th></tr>
            </thead>
            <tbody>
              {Object.keys(TOOL_POLICY).map((t) => {
                const v = agent.tools[t] ?? { calls: 0, denied: 0, confirm: 0 };
                return (
                  <tr key={t} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2"><div className="font-mono text-[12px]">{t}</div><div className="text-[10.5px] text-muted">{TOOL_POLICY[t]}</div></td>
                    <td className="text-right px-2 font-mono">{v.calls}</td>
                    <td className="text-right px-4 font-mono">
                      <span className={v.confirm ? "text-warn" : "text-muted"}>{v.confirm}</span>
                      <span className="text-muted"> / </span>
                      <span className={v.denied ? "text-block" : "text-muted"}>{v.denied}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>

        {/* OWASP */}
        <Panel title="Blocked by OWASP category">
          <Owasp data={stats?.by_owasp ?? {}} />
        </Panel>

        {/* Live */}
        <Panel title={<span className="flex items-center gap-2">{connected ? <span className="sl-live-dot" /> : null}Live stream</span>}
          right={<Link href="/live" className="text-brand text-[11.5px]">open feed →</Link>} bodyClass="p-0">
          <ul className="max-h-[320px] overflow-auto sl-scroll divide-y divide-line/60">
            {items.length === 0 && <li className="p-4 text-muted text-[12.5px]">Waiting for activity. Chat as a customer or run the Attack lab.</li>}
            {items.slice(0, 30).map((x) => <MiniRow key={x.id} x={x} />)}
          </ul>
        </Panel>
      </div>
    </Shell>
  );
}

function Kpi({ label, value, hint, accent }: { label: string; value: any; hint?: string; accent?: string }) {
  return (
    <div className="sl-panel sl-kpi px-4 py-3" style={{ ["--kpi" as any]: accent }}>
      <div className="text-[10.5px] uppercase tracking-[.14em] text-muted">{label}</div>
      <div className="text-[26px] font-semibold tabular-nums leading-tight mt-0.5">{value}</div>
      {hint && <div className="text-[11px] text-muted truncate">{hint}</div>}
    </div>
  );
}

function FunnelRow({ name, color, entered, decided, blocked, total, note }: {
  name: string; color: string; entered: number; decided: number; blocked: number; total: number; note: string;
}) {
  const pct = (n: number) => (total ? (n / total) * 100 : 0);
  const allowed = Math.max(0, decided - blocked);
  return (
    <div className="group">
      <div className="flex items-baseline justify-between text-[12.5px] mb-1">
        <span className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: color }} />{name}</span>
        <span className="text-muted text-[11px]">{note}</span>
      </div>
      <div className="relative h-7 rounded-md bg-bg border border-line overflow-hidden" title={`${entered} reached · ${allowed} allowed here · ${blocked} blocked here`}>
        <div className="absolute inset-y-0 left-0 rounded-r" style={{ width: `${pct(entered)}%`, background: color, opacity: 0.22 }} />
        <div className="absolute bottom-0 left-0 h-[3px] flex gap-[2px]" style={{ width: `${pct(decided)}%` }}>
          {allowed > 0 && <div className="h-full bg-ok" style={{ flex: allowed }} />}
          {blocked > 0 && <div className="h-full bg-block" style={{ flex: blocked }} />}
        </div>
        <div className="absolute inset-0 flex items-center justify-between px-2.5 text-[11.5px] font-mono">
          <span>{entered} reached</span>
          <span><span className="text-ok">{allowed} allow</span> · <span className="text-block">{blocked} block</span></span>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v, mono }: { k: string; v: any; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted shrink-0">{k}</dt>
      <dd className={`text-right truncate ${mono ? "font-mono text-[12px]" : ""}`} title={String(v)}>{String(v)}</dd>
    </div>
  );
}

function Owasp({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map((e) => e[1]));
  if (!entries.length) return <div className="text-muted text-[12.5px]">No blocks recorded yet.</div>;
  return (
    <ul className="space-y-2.5">
      {entries.map(([k, v]) => (
        <li key={k} title={`${k}: ${v} blocked`}>
          <div className="flex justify-between text-[12px]"><span><b className="font-mono font-medium">{k}</b> <span className="text-muted">{OWASP_NAME[k] ?? ""}</span></span><span className="font-mono">{v}</span></div>
          <div className="mt-1 h-1.5 rounded-full bg-line overflow-hidden"><div className="h-full bg-block/80 rounded-r-full" style={{ width: `${(v / max) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

function MiniRow({ x }: { x: FeedItem }) {
  if (isAgent(x)) {
    const label = x.event === "tool_call" ? `tool ${x.tool}` : x.event === "gate" ? `L4 ${x.status} · ${x.origin} → ${x.tool}`
      : x.event === "upload" ? `upload ${x.filename}` : x.event === "output_guard" ? `output guard ${x.owasp?.join(",")}` : `turn · ${x.intent}`;
    const bad = x.status === "denied" || x.status === "deny" || x.blocked || x.status === "block" || x.status === "quarantined";
    const tone = bad ? "text-block" : x.status === "confirm" || x.status === "fixed" || x.status === "partial" ? "text-warn" : "text-agent";
    return (
      <li className="sl-row-in px-4 py-2 flex items-center gap-3 text-[12px]">
        <span className={`font-mono text-[10.5px] w-14 shrink-0 ${tone}`}>AGENT</span>
        <span className="truncate flex-1">{label}{x.detail ? <span className="text-muted"> · {x.detail}</span> : null}</span>
        <span className="text-muted text-[10.5px] shrink-0">{timeAgo(tsOf(x))}</span>
      </li>
    );
  }
  return (
    <li className="sl-row-in px-4 py-2 flex items-center gap-3 text-[12px]">
      <span className="w-14 shrink-0"><VerdictBadge verdict={x.verdict} /></span>
      <span className="truncate flex-1 text-ink/90">{x.text_preview}</span>
      <LayerTag layer={x.layer} />
      <span className="text-muted text-[10.5px] shrink-0 w-14 text-right">{timeAgo(tsOf(x))}</span>
    </li>
  );
}
