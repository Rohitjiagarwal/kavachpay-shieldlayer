"use client";
/**
 * Recorded demos: every mission replayed from a real run of the pipeline
 * (scripts/record_demos.py). Runs entirely in the browser: no sign-in, no
 * backend calls, no tokens.
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { TurnEvent } from "@/lib/api";
import TurnProgress from "@/components/TurnProgress";
import { KavachLogo, KavachMark, ShieldLayerMark } from "@/components/Brand";
import { BotMessage, LAYER_CHIP, UploadCard, applyUploadEvent, botFromResponse, type Msg } from "@/components/ChatParts";
import { MISSIONS } from "@/lib/missions";
import recordings from "@/lib/demo-recordings.json";

type Step =
  | { kind: "chat"; prompt: string; events: TurnEvent[]; final: any }
  | { kind: "upload"; filename: string; events: any[]; final: any }
  | { kind: "confirm"; result: { ok: boolean; message: string } }
  | { kind: "switch"; to: string };
type Recording = {
  recorded_at: string;
  chat_model: { provider: string; model: string };
  layer2?: string;
  judge?: string;
  scenarios: { id: string; steps: Step[] }[];
};
const REC = recordings as unknown as Recording;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** Real gaps between events, squeezed so a replay takes seconds, not minutes. */
const gap = (ev: any, prev: number) => {
  const real = Math.max(0, (ev.t ?? prev) - prev);
  const cap = ev.type === "model" ? 260 : ev.stage === "parse" ? 900 : 420;
  return Math.min(cap, Math.max(70, real));
};

export default function Demos() {
  const [sel, setSel] = useState(REC.scenarios[0]?.id ?? "m1");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [live, setLive] = useState<TurnEvent[] | null>(null);
  const [liveStart, setLiveStart] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [seen, setSeen] = useState<Record<string, boolean>>({});
  const run = useRef(0);
  const instant = useRef(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, live?.length]);
  useEffect(() => () => { run.current++; }, []); // stop timers on unmount

  const mission = MISSIONS.find((m) => m.id === sel);
  const scenario = REC.scenarios.find((s) => s.id === sel);

  function select(id: string) {
    run.current++;
    setSel(id); setMsgs([]); setLive(null); setOpen(null); setPlaying(false);
  }

  async function play(id: string) {
    const my = ++run.current;
    instant.current = false;
    setSel(id); setMsgs([]); setLive(null); setOpen(null); setPlaying(true);
    const sc = REC.scenarios.find((s) => s.id === id);
    if (!sc) return;
    const alive = () => run.current === my;
    const wait = async (ms: number) => { if (!instant.current) await sleep(ms); return alive(); };
    const local: Msg[] = [];
    const show = () => setMsgs([...local]);

    for (const st of sc.steps) {
      if (!alive()) return;
      if (st.kind === "chat") {
        local.push({ role: "user", text: st.prompt }); show();
        if (!(await wait(500))) return;
        const shown: TurnEvent[] = [];
        let prev = 0;
        setLive([]); setLiveStart(Date.now());
        for (const ev of st.events) {
          if (!(await wait(gap(ev, prev)))) return;
          prev = ev.t ?? prev;
          shown.push(ev); setLive([...shown]);
        }
        if (!(await wait(300))) return;
        setLive(null);
        local.push(botFromResponse(st.final, st.events)); show();
        setOpen(local.length - 1);
      } else if (st.kind === "upload") {
        const idx = local.length;
        local.push({ role: "upload", text: st.filename, upload: { filename: st.filename, stage: "uploading", chunks: [] } });
        show();
        let prev = 0;
        for (const ev of [...st.events, st.final]) {
          if (!(await wait(gap(ev, prev)))) return;
          prev = ev.t ?? prev;
          const u = { ...local[idx].upload!, chunks: [...local[idx].upload!.chunks] };
          applyUploadEvent(u, ev);
          local[idx] = { ...local[idx], upload: u }; show();
        }
      } else if (st.kind === "confirm") {
        if (!(await wait(1100))) return;
        const i = [...local].reverse().findIndex((m) => m.role === "bot" && m.confirm);
        if (i >= 0) { const j = local.length - 1 - i; local[j] = { ...local[j], confirmed: st.result.message }; show(); }
      } else if (st.kind === "switch") {
        if (!(await wait(700))) return;
        local.push({ role: "system", text: st.to === "admin" ? "Signed in as Security Admin · new signed session, role = admin" : "Signed in as the customer" });
        show();
      }
      if (!(await wait(700))) return;
    }
    if (alive()) { setPlaying(false); setSeen((s) => ({ ...s, [id]: true })); }
  }

  return (
    <div className="pn-root min-h-screen w-full">
      <header className="flex items-center gap-3 px-4 md:px-8 py-3 border-b border-[var(--pn-line)]">
        <KavachLogo size={34} />
        <span className="hidden sm:inline text-[var(--pn-muted)]">/</span>
        <span className="hidden sm:inline font-semibold">Recorded demos</span>
        <span className="flex-1" />
        <Link href="/login" className="rounded-lg px-3.5 py-1.5 text-[13px] font-semibold bg-gradient-to-r from-[#14b8a6] to-[#4f46e5] hover:brightness-110">Try it live →</Link>
      </header>

      <div className="max-w-6xl mx-auto px-4 md:px-8 py-6 grid lg:grid-cols-[320px_1fr] gap-6">
        {/* ---------- scenario list ---------- */}
        <aside className="flex flex-col gap-3">
          <div className="pn-glass rounded-2xl p-4">
            <div className="flex items-center gap-2 font-semibold"><ShieldLayerMark size={18} /> 8 attacks, replayed</div>
            <p className="text-[12.5px] text-[var(--pn-muted)] mt-1.5 leading-relaxed">
              Real runs of the KavachPay pipeline, recorded step by step and replayed in your browser.
              Nothing is sent to a server and no tokens are used.
            </p>
          </div>
          <nav className="flex flex-col gap-1.5" aria-label="Scenarios">
            {MISSIONS.map((m, n) => {
              const on = sel === m.id;
              return (
                <button key={m.id} onClick={() => select(m.id)} aria-current={on}
                  className={`text-left rounded-xl border px-3 py-2.5 flex items-center gap-2.5 transition ${on ? "border-[#5eead4]/45 bg-white/[.05]" : "border-[var(--pn-line)] bg-white/[.015] hover:border-[#5eead4]/30"}`}>
                  <span className={`w-6 h-6 shrink-0 rounded-lg grid place-items-center text-[11px] font-bold ${seen[m.id] ? "bg-[#2ee6a6]/20 text-[#2ee6a6]" : "bg-white/5 text-[var(--pn-muted)]"}`}>{seen[m.id] ? "✓" : n + 1}</span>
                  <span className="flex-1 min-w-0 text-[13px] font-medium truncate">{m.title}</span>
                  <span className="flex gap-1">{m.layers.slice(0, 2).map((l) => <span key={l} className={`text-[9.5px] font-mono px-1.5 py-[1px] rounded border ${LAYER_CHIP[l]}`}>{l}</span>)}</span>
                </button>
              );
            })}
          </nav>
          <p className="text-[11px] text-[var(--pn-muted)] leading-relaxed px-1">
            Recorded {REC.recorded_at} on a local install · replies by {REC.chat_model.provider} <span className="font-mono">{REC.chat_model.model}</span> ·
            L2 extractor: {REC.layer2 ?? REC.judge ?? "Heuristic"}. Zero-judge deterministic pipeline.
          </p>
        </aside>

        {/* ---------- replay ---------- */}
        <main className="min-w-0 flex flex-col gap-4">
          {mission && (
            <div className="pn-glass rounded-2xl p-4 md:p-5">
              <div className="flex flex-wrap items-start gap-3">
                <div className="flex-1 min-w-[220px]">
                  <div className="text-[11px] uppercase tracking-[.16em] text-[var(--pn-muted)]">Mission {MISSIONS.indexOf(mission) + 1}</div>
                  <h1 className="text-xl font-bold tracking-tight mt-0.5">{mission.title}</h1>
                  <p className="text-[13.5px] text-[#c9d0e6] mt-1">{mission.goal}</p>
                </div>
                <div className="flex gap-2">
                  {playing ? (
                    <button onClick={() => { instant.current = true; }} className="pn-chip rounded-xl px-4 py-2 text-[13px]">⏭ Skip to the end</button>
                  ) : (
                    <button onClick={() => play(sel)} className="rounded-xl px-5 py-2 text-[13.5px] font-semibold bg-gradient-to-r from-[#14b8a6] to-[#4f46e5] shadow-lg shadow-[#4f46e5]/30 hover:brightness-110">
                      {msgs.length ? "↺ Replay" : "▶ Play"}</button>
                  )}
                </div>
              </div>
              <details className="mt-3" open={seen[sel]}>
                <summary className="cursor-pointer text-[12px] text-[var(--pn-muted)] hover:text-white">What this proves</summary>
                <p className="mt-1.5 text-[13px] leading-relaxed text-[#b9c2dc]">{mission.talk}</p>
                {seen[sel] && <div className="mt-1.5 font-mono text-[12px] text-[#2ee6a6]">{mission.flag}</div>}
              </details>
            </div>
          )}

          <div className="pn-glass rounded-2xl p-4 md:p-6 min-h-[420px] flex flex-col gap-5">
            {!scenario && <p className="text-[var(--pn-muted)] text-sm">No recording for this mission yet. Run <span className="font-mono">python scripts/record_demos.py</span>.</p>}
            {scenario && msgs.length === 0 && !playing && (
              <div className="m-auto text-center py-10">
                <KavachMark size={54} className="mx-auto" />
                <p className="mt-4 text-[var(--pn-muted)] text-[14px] max-w-sm">Press play to watch this attack hit the 4 layers, step by step.</p>
                <button onClick={() => play(sel)} className="mt-4 rounded-xl px-5 py-2 text-[13.5px] font-semibold bg-gradient-to-r from-[#14b8a6] to-[#4f46e5] hover:brightness-110">▶ Play</button>
              </div>
            )}
            {msgs.map((m, i) => m.role === "user" ? (
              <div key={i} className="pn-fade-in self-end max-w-[85%] md:max-w-[75%]">
                <div className="pn-bubble-user text-white rounded-2xl rounded-br-md px-4 py-2.5 text-[14.5px] leading-relaxed whitespace-pre-wrap break-words">{m.text}</div>
              </div>
            ) : m.role === "upload" && m.upload ? (
              <UploadCard key={i} u={m.upload} />
            ) : m.role === "system" ? (
              <div key={i} className="pn-fade-in flex items-center gap-3 text-[11.5px] text-[#67e8f9]">
                <span className="flex-1 h-px bg-[#22d3ee]/25" />⇄ {m.text}<span className="flex-1 h-px bg-[#22d3ee]/25" />
              </div>
            ) : (
              <BotMessage key={i} m={m} open={open === i} onToggle={() => setOpen(open === i ? null : i)} />
            ))}
            {live && (
              <div className="self-start w-full flex gap-3 pn-fade-in">
                <KavachMark size={30} className="shrink-0 mt-0.5" />
                <div className="pn-bubble-bot rounded-2xl rounded-tl-md px-4 py-3 w-full max-w-[540px]" aria-live="polite">
                  <TurnProgress events={live} running startedAt={liveStart} />
                  <div className="mt-2 text-[10.5px] text-[var(--pn-muted)]">sped-up replay · the ms next to each step are the real timings</div>
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </main>
      </div>
    </div>
  );
}
