"use client";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Panel } from "@/components/VerdictBadge";
import { api } from "@/lib/api";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const ORDER = ["none", "layer1", "layer1+layer2", "all3", "regex", "regex+clf", "judge_only"];

export default function Scorecard() {
  const [data, setData] = useState<any>(null);
  const [view, setView] = useState<"chart" | "table">("chart");

  useEffect(() => { api.scorecard().then(setData).catch(() => setData({ available: false })); }, []);

  if (!data) return <Shell title="Scorecard"><div className="text-muted">Loading…</div></Shell>;
  if (!data.available)
    return <Shell title="Scorecard"><Panel><div className="text-muted text-[13px]">No scorecard yet. Run <code className="text-brand">python -m attacks.run_attacks</code> to measure every funnel setup against the attack library.</div></Panel></Shell>;

  const setups = data.setups || {};
  const keys = ORDER.filter((k) => setups[k]);
  const chart = keys.map((k) => ({
    name: setups[k].label,
    "Attacks blocked": setups[k].attacks_blocked_pct,
    "Safe wrongly blocked": setups[k].safe_blocked_pct,
  }));
  const best = setups.all3 || setups.full || setups[keys[keys.length - 1]];

  return (
    <Shell title="Scorecard" subtitle={`${data.n_attacks || 0} attacks and ${data.n_safe || 0} safe messages, replayed against each funnel setup`}
      actions={<div className="flex gap-1">{(["chart", "table"] as const).map((v) => <button key={v} className="sl-tab" data-on={view === v} onClick={() => setView(v)}>{v}</button>)}</div>}>
      {best && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <Tile k="Attacks blocked (3-Layer Pipeline)" v={`${best.attacks_blocked_pct}%`} />
          <Tile k="Safe wrongly blocked" v={`${best.safe_blocked_pct}%`} />
          <Tile k="p95 latency" v={`${best.p95_ms} ms`} />
          <Tile k="Zero-Judge Invariants" v="100% deterministic" />
        </div>
      )}
      <p className="text-[12px] text-muted mb-3 font-mono">architecture: 3-layer zero-judge pipeline (deterministic funnel + intent extractor + policy gate)</p>

      {view === "chart" ? (
        <Panel title="Blocked vs wrongly blocked, by setup">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chart} barGap={2}>
              <CartesianGrid vertical={false} stroke="var(--line)" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={{ stroke: "var(--line)" }} tickLine={false} />
              <YAxis unit="%" tick={{ fontSize: 11, fill: "var(--muted)" }} domain={[0, 100]} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "rgba(34,211,238,.06)" }} contentStyle={{ background: "var(--panel2)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12, color: "var(--ink)" }} />
              <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />
              <Bar dataKey="Attacks blocked" fill="var(--ok)" radius={[4, 4, 0, 0]} maxBarSize={36} />
              <Bar dataKey="Safe wrongly blocked" fill="var(--block)" radius={[4, 4, 0, 0]} maxBarSize={36} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      ) : (
        <Panel bodyClass="p-0">
          <table className="w-full text-[12.5px]">
            <thead className="text-[10.5px] uppercase tracking-[.12em] text-muted"><tr className="border-b border-line">
              {["Setup", "Attacks blocked", "Safe wrongly blocked", "p95 ms", "L3 block share"].map((h) => <th key={h} className="text-left font-medium px-4 py-2">{h}</th>)}
            </tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k} className={`border-b border-line/60 last:border-0 ${k === "all3" ? "bg-brand/5" : ""}`}>
                  <td className="px-4 py-2">{setups[k].label}{k === "all3" && <span className="ml-2 text-brand text-[10.5px] font-mono">deployed</span>}</td>
                  <td className="px-4 font-mono">{setups[k].attacks_blocked_pct}%</td>
                  <td className="px-4 font-mono">{setups[k].safe_blocked_pct}%</td>
                  <td className="px-4 font-mono">{setups[k].p95_ms}</td>
                  <td className="px-4 font-mono">{setups[k].l3_block_share_pct ?? setups[k].judge_share_pct ?? 0}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {data.per_owasp && (
        <Panel title="All 3 layers: blocked per OWASP id" className="mt-4">
          <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2.5">
            {Object.entries(data.per_owasp).map(([k, v]: any) => (
              <li key={k} title={`${k}: ${v}%`}>
                <div className="flex justify-between text-[12px]"><span className="font-mono">{k}</span><span className="font-mono">{v}%</span></div>
                <div className="mt-1 h-1.5 rounded-full bg-line overflow-hidden"><div className="h-full bg-ok/80 rounded-r-full" style={{ width: `${v}%` }} /></div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </Shell>
  );
}

function Tile({ k, v }: { k: string; v: any }) {
  return (
    <div className="sl-panel px-4 py-3">
      <div className="text-[10.5px] uppercase tracking-[.14em] text-muted">{k}</div>
      <div className="text-[24px] font-semibold tabular-nums">{v}</div>
    </div>
  );
}
