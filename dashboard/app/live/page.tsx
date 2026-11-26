"use client";
import { useMemo, useState } from "react";
import Shell from "@/components/Shell";
import { LayerTag, Panel, VerdictBadge } from "@/components/VerdictBadge";
import { isAgent, tsOf, useFeed, type FeedItem } from "@/lib/useFeed";

const KINDS = ["all", "scans", "agent"] as const;
const VERDICTS = ["any", "block", "allow"] as const;
const LAYERS = ["any", "layer1", "layer2", "layer3", "provenance"] as const;
const SOURCES = ["any", "user", "document", "tool"] as const;

export default function Live() {
  const { items, connected, paused, setPaused, clear } = useFeed(500);
  const [kind, setKind] = useState<(typeof KINDS)[number]>("all");
  const [verdict, setVerdict] = useState<(typeof VERDICTS)[number]>("any");
  const [layer, setLayer] = useState<(typeof LAYERS)[number]>("any");
  const [source, setSource] = useState<(typeof SOURCES)[number]>("any");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const shown = useMemo(() => items.filter((x) => {
    const agent = isAgent(x);
    if (kind === "scans" && agent) return false;
    if (kind === "agent" && !agent) return false;
    if (!agent) {
      if (verdict !== "any" && x.verdict !== verdict) return false;
      if (layer !== "any" && x.layer !== layer) return false;
      if (source !== "any" && x.source !== source) return false;
    } else if (verdict === "block" && !(x.blocked || x.status === "denied" || x.status === "block")) return false;
    if (q && !JSON.stringify(x).toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  }), [items, kind, verdict, layer, source, q]);

  const blocks = items.filter((x) => !isAgent(x) && x.verdict === "block").length;

  return (
    <Shell title="Live activity" subtitle="Funnel verdicts and agent actions (tool calls, confirmations, output guards, turns) as they happen."
      actions={<>
        <span className="flex items-center gap-1.5 text-[12px] text-muted mr-1">
          {connected ? <span className="sl-live-dot" /> : <span className="w-[7px] h-[7px] rounded-full bg-block" />}
          {connected ? (paused ? "paused" : "streaming") : "disconnected"}
        </span>
        <button className="sl-btn" onClick={() => setPaused(!paused)}>{paused ? "▶ Resume" : "❚❚ Pause"}</button>
        <button className="sl-btn" onClick={clear}>Clear</button>
      </>}>
      <Panel bodyClass="p-0">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 border-b border-line text-[12px]">
          <Seg label="Type" opts={KINDS} v={kind} set={setKind} />
          <Seg label="Verdict" opts={VERDICTS} v={verdict} set={setVerdict} />
          <Seg label="Layer" opts={LAYERS} v={layer} set={setLayer} />
          <Seg label="Source" opts={SOURCES} v={source} set={setSource} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search text, tool, OWASP id, session…"
            className="sl-input px-3 py-1.5 text-[12.5px] flex-1 min-w-[200px]" />
          <span className="text-muted font-mono">{shown.length}/{items.length} · {blocks} blocks</span>
        </div>
        <div className="hidden md:grid grid-cols-[92px_96px_1fr_110px_90px_70px] gap-3 px-4 py-2 text-[10.5px] uppercase tracking-[.12em] text-muted border-b border-line">
          <span>Time</span><span>Verdict</span><span>Event</span><span>Layer / tool</span><span>Source</span><span className="text-right">Latency</span>
        </div>
        <ul className="divide-y divide-line/60 max-h-[calc(100vh-290px)] overflow-auto sl-scroll">
          {shown.length === 0 && <li className="p-6 text-muted text-[13px]">Nothing matches yet. Chat as a customer, upload a document, or fire a payload in the Attack lab.</li>}
          {shown.map((x) => <FeedRow key={x.id} x={x} open={open === x.id} toggle={() => setOpen(open === x.id ? null : x.id)} />)}
        </ul>
      </Panel>
    </Shell>
  );
}

function Seg<T extends string>({ label, opts, v, set }: { label: string; opts: readonly T[]; v: T; set: (x: T) => void }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-muted mr-1">{label}</span>
      {opts.map((o) => <button key={o} className="sl-tab" data-on={v === o} onClick={() => set(o)}>{o}</button>)}
    </div>
  );
}

function FeedRow({ x, open, toggle }: { x: FeedItem; open: boolean; toggle: () => void }) {
  const time = new Date(tsOf(x)).toLocaleTimeString([], { hour12: false });
  const agent = isAgent(x);
  let badge, text, tag, src, lat;
  if (agent) {
    const bad = x.blocked || x.status === "denied" || x.status === "deny" || x.status === "block" || x.status === "quarantined";
    const warn = x.status === "confirm" || x.status === "fixed" || x.status === "partial";
    badge = <span className={`inline-flex rounded px-1.5 py-0.5 text-[11px] font-mono border ${bad ? "text-block border-block/30 bg-block/10" : warn ? "text-warn border-warn/30 bg-warn/10" : "text-agent border-agent/30 bg-agent/10"}`}>
      {x.event === "gate" ? (bad ? "L4 DENY" : warn ? "L4 HOLD" : "L4 ALLOW") : bad ? "STOPPED" : x.status === "confirm" ? "HELD" : x.status === "fixed" ? "FIXED" : "AGENT"}</span>;
    text = x.event === "gate" ? <>L4 origin gate · <b className="font-medium">{x.origin}</b> → {x.tool} <span className="text-muted">· {x.detail}</span></>
      : x.event === "upload" ? <>File upload <b className="font-medium">{x.filename}</b> <span className="text-muted">· {x.detail}</span></>
      : x.event === "tool_call" ? <>Tool call <span className="text-muted">· {x.detail || x.status}</span></>
      : x.event === "output_guard" ? <>Output guard <span className="text-muted">· {x.detail}</span></>
      : <>Turn complete <span className="text-muted">· intent {x.intent}{x.tools?.length ? ` · ${x.tools.length} tool(s)` : ""}{x.model ? ` · ${x.model}` : ""}</span></>;
    tag = <span className="font-mono text-[11px] truncate">{x.tool ?? (x.owasp ? x.owasp.join(",") : x.shield_layer ?? "—")}</span>;
    src = <span className="text-muted">cust {x.customer_id ?? "—"}</span>;
    lat = x.ms != null ? `${Math.round(x.ms)}ms` : "";
  } else {
    badge = <VerdictBadge verdict={x.verdict} />;
    text = <span className="truncate">{x.text_preview}</span>;
    tag = <LayerTag layer={x.layer} />;
    src = <span className="text-muted">{x.source}{x.owasp && x.owasp !== "NONE" ? <b className="text-block font-mono font-medium"> {x.owasp}</b> : null}</span>;
    lat = x.latency_ms != null ? `${x.latency_ms < 10 ? x.latency_ms.toFixed(1) : Math.round(x.latency_ms)}ms` : "";
  }
  return (
    <li className="sl-row-in">
      <button onClick={toggle} className="w-full text-left grid grid-cols-[70px_1fr] md:grid-cols-[92px_96px_1fr_110px_90px_70px] gap-x-3 gap-y-1 items-center px-4 py-2 text-[12.5px] hover:bg-panel2/60">
        <span className="font-mono text-muted text-[11.5px]">{time}</span>
        <span>{badge}</span>
        <span className="min-w-0 truncate col-span-2 md:col-span-1">{text}</span>
        <span className="hidden md:block">{tag}</span>
        <span className="hidden md:block text-[12px]">{src}</span>
        <span className="hidden md:block text-right font-mono text-muted text-[11.5px]">{lat}</span>
      </button>
      {open && (
        <div className="px-4 pb-3 md:pl-[123px]">
          <div className="rounded-md border border-line bg-bg/70 p-3 text-[12px] grid gap-1.5">
            {agent ? (
              <>
                <KV k="event" v={x.event} />
                {x.tool && <KV k="tool" v={x.tool} />}
                {x.args && Object.keys(x.args).length > 0 && <KV k="args" v={JSON.stringify(x.args)} />}
                {x.origin && <KV k="origin" v={x.origin} />}
                {x.arg_origins && Object.keys(x.arg_origins).length > 0 && <KV k="arg origin" v={JSON.stringify(x.arg_origins)} />}
                {x.rule && <KV k="rule" v={x.rule} />}
                {x.status && <KV k="status" v={x.status} />}
                {x.detail && <KV k="detail" v={x.detail} />}
                {x.owasp && <KV k="owasp" v={x.owasp.join(", ")} />}
                {x.shield_layer && <KV k="shield" v={`decided at ${x.shield_layer}`} />}
                <KV k="session" v={x.session_id ?? "—"} />
              </>
            ) : (
              <>
                <KV k="preview" v={x.text_preview} />
                <KV k="reason" v={x.reason || "—"} />
                {x.score != null && <KV k="score" v={`${Number(x.score).toFixed(3)} (raw ${x.raw_score ?? "—"})`} />}
                {x.rule_id && <KV k="rule" v={x.rule_id} />}
                {x.judge_provider && <KV k="judge" v={`${x.judge_provider} ${x.judge_model ?? ""}`} />}
                {x.chunk_id && <KV k="chunk" v={x.chunk_id} />}
                <KV k="sha256" v={x.text_sha256?.slice(0, 16) + "…"} />
                {x.session_id && <KV k="session" v={x.session_id} />}
              </>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function KV({ k, v }: { k: string; v: any }) {
  return <div className="grid grid-cols-[80px_1fr] gap-3"><span className="text-muted font-mono">{k}</span><span className="break-words">{String(v)}</span></div>;
}
