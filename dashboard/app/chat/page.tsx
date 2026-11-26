"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type DemoStatus, type TurnEvent } from "@/lib/api";
import TurnProgress from "@/components/TurnProgress";
import { BRAND, KavachLogo, KavachMark, ShieldLayerMark } from "@/components/Brand";
import { MISSIONS, loadDone, saveDone, type Mission, type Turn } from "@/lib/missions";
import { BotMessage, UploadCard, applyUploadEvent, botFromResponse, type Msg, type Txn, type UploadState, LAYER_CHIP, inr } from "@/components/ChatParts";
import KeyDialog from "@/components/KeyDialog";
import { useKey } from "@/lib/byok";

export default function Chat() {
  const router = useRouter();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [me, setMe] = useState<{ role: string; account: any; transactions: Txn[]; tainted?: boolean } | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [authErr, setAuthErr] = useState(false);
  const [openTrace, setOpenTrace] = useState<number | null>(null);
  const [live, setLive] = useState<TurnEvent[]>([]);
  const [startedAt, setStartedAt] = useState(0);
  const [done, setDone] = useState<Record<string, number>>({});
  const [openMission, setOpenMission] = useState<string | null>("m1");
  const [toast, setToast] = useState<Mission | null>(null);
  const [tainted, setTainted] = useState(false);
  const [sampleMsg, setSampleMsg] = useState<Record<string, string>>({});
  const [quota, setQuota] = useState<DemoStatus | null>(null);
  const [keyOpen, setKeyOpen] = useState(false);
  const visitorKey = useKey();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const role = me?.role ?? "user";
  const refreshMe = () => api.me().then((m) => { setMe(m); setTainted(!!m.tainted); }).catch(() => setAuthErr(true));
  const refreshQuota = () => api.demoStatus().then(setQuota).catch(() => {});
  useEffect(() => { refreshMe(); refreshQuota(); api.health().then(setHealth).catch(() => {}); setDone(loadDone()); }, []);
  // public demo: free requests used up and no key of their own -> chat is read-only
  const locked = !!quota?.public && (quota.remaining ?? 1) <= 0 && !visitorKey;
  const quotaNote = (e: any) => {
    if (e instanceof ApiError && e.quota) { refreshQuota(); return true; }
    return false;
  };
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, live.length]);

  function checkMissions(t: Turn) {
    setDone((d) => {
      const hit = MISSIONS.find((m) => !d[m.id] && m.done(t));
      if (!hit) return d;
      const nd = { ...d, [hit.id]: Date.now() };
      saveDone(nd);
      setToast(hit);
      setTimeout(() => setToast(null), 6000);
      const next = MISSIONS.find((m) => !nd[m.id]);
      if (next) setOpenMission(next.id);
      return nd;
    });
  }

  const pendingTxn = me?.transactions?.find((t) => t.status === "pending")?.txn_id;
  const resolvePrompt = (p: string) => p === "__PENDING_TXN__"
    ? `What happened with transaction ${pendingTxn ?? "(open the pending payment from your activity)"}?` : p;

  async function send(text?: string) {
    const q = (text ?? input).trim();
    if (!q || busy || locked) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setBusy(true); setLive([]); setStartedAt(Date.now());
    const trace: TurnEvent[] = [];
    try {
      const r = await api.chatStream(q, (ev) => { if (ev.type !== "final") { trace.push(ev); setLive((l) => [...l, ev]); } });
      setMsgs((m) => [...m, botFromResponse(r, trace)]);
      checkMissions({ kind: "chat", r, role });
      if (r.tools?.length) refreshMe();
    } catch (e: any) {
      if (String(e?.message || e).startsWith("401")) setAuthErr(true);
      const text = quotaNote(e) ? `${e.detail?.message ?? "Free requests used up."} Watch the recorded demos, or add your own Gemini key to keep going.`
        : e instanceof ApiError && e.status === 400 ? String(e.detail)
        : "I couldn't reach the KavachPay servers. Please try again in a moment.";
      setMsgs((m) => [...m, { role: "bot", text, blocked: true }]);
    }
    refreshQuota();
    setBusy(false); setLive([]);
    inputRef.current?.focus();
  }

  async function attach(file: File) {
    if (busy || locked) return;
    setBusy(true);
    const idx = msgs.length;
    const st: UploadState = { filename: file.name, stage: "uploading", chunks: [] };
    setMsgs((m) => [...m, { role: "upload", text: file.name, upload: { ...st } }]);
    const update = (f: (u: UploadState) => void) =>
      setMsgs((m) => m.map((x, j) => {
        if (j !== idx || !x.upload) return x;
        const u = { ...x.upload, chunks: [...x.upload.chunks] };
        f(u);
        return { ...x, upload: u };
      }));
    try {
      const final = await api.uploadStream(file, (ev) => update((u) => applyUploadEvent(u, ev)));
      setTainted(true);
      checkMissions({ kind: "upload", r: final, role });
    } catch (e: any) {
      update((u) => { u.error = quotaNote(e) ? "Free requests used up: this file was not scanned." : String(e?.message || e); });
    }
    refreshQuota();
    setBusy(false);
  }

  async function fetchSample(name: string): Promise<File> {
    const r = await fetch(api.sampleUrl(name), { credentials: "include" });
    if (!r.ok) throw new Error(`could not fetch sample (${r.status})`);
    return new File([await r.blob()], name, { type: "application/pdf" });
  }

  /** One click: fetch the demo PDF and attach it, same path as the 📎 button. */
  async function attachSample(name: string) {
    try {
      setSampleMsg((m) => ({ ...m, [name]: "fetching…" }));
      const f = await fetchSample(name);
      setSampleMsg((m) => ({ ...m, [name]: "attached below ↓" }));
      await attach(f);
    } catch (e: any) {
      setSampleMsg((m) => ({ ...m, [name]: `failed: ${e?.message || e}` }));
    }
  }

  /** Save via a same-page blob link, which works where a cross-port link is ignored. */
  async function saveSample(name: string) {
    try {
      const f = await fetchSample(name);
      const url = URL.createObjectURL(f);
      const a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      setSampleMsg((m) => ({ ...m, [name]: "saved to your Downloads folder (if your browser allows downloads)" }));
    } catch (e: any) {
      setSampleMsg((m) => ({ ...m, [name]: `failed: ${e?.message || e}` }));
    }
  }

  async function confirm(i: number, token: string) {
    try {
      const r = await api.confirm(token);
      setMsgs((m) => m.map((x, j) => (j === i ? { ...x, confirmed: r.message } : x)));
      refreshMe();
    } catch (e) {
      setMsgs((m) => m.map((x, j) => (j === i ? { ...x, confirmed: "Couldn't confirm: " + e } : x)));
    }
  }

  async function newChat() { await api.reset().catch(() => {}); setMsgs([]); setTainted(false); }
  async function switchTo(r: "admin" | "user") { await api.login(r === "admin" ? 0 : 1); setMsgs([]); setTainted(false); await refreshMe(); }

  const acct = me?.account;
  const firstName = role === "admin" ? "Admin" : acct?.name?.split(" ")[0] ?? "there";
  const modelName = health?.chat_model?.model || health?.chat_model?.provider || "…";
  const doneCount = MISSIONS.filter((m) => done[m.id]).length;

  return (
    <div className="pn-root min-h-screen w-full flex">
      {/* ---------- Left rail ---------- */}
      <aside className="hidden lg:flex w-[360px] shrink-0 flex-col gap-4 p-5 border-r border-[var(--pn-line)] h-screen">
        <KavachLogo size={38} />

        {role === "admin" ? (
          <div className="rounded-2xl p-4 border border-[#22d3ee]/30 bg-[#22d3ee]/[.06]">
            <div className="flex items-center gap-2.5"><ShieldLayerMark size={24} /><div>
              <div className="font-semibold text-[14px]">Security Admin</div>
              <div className="text-[11px] text-[var(--pn-muted)]">session role: <b className="text-[#67e8f9]">admin</b> · admin tools unlocked</div></div></div>
            <Link href="/console" className="mt-3 block text-center text-[12.5px] rounded-lg py-1.5 bg-[#22d3ee] text-[#04161b] font-semibold">Open security console →</Link>
          </div>
        ) : (
          <div className="pn-card pn-shine rounded-2xl p-4 text-white">
            <div className="flex justify-between items-start">
              <div className="text-[10.5px] uppercase tracking-[.18em] opacity-80">Wallet balance</div>
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${acct?.upi_status === "blocked" ? "bg-[#ff5d7a]" : "bg-white/20"}`}>UPI {acct?.upi_status ?? "…"}</span>
            </div>
            <div className="text-[26px] font-bold mt-0.5 tracking-tight tabular-nums">{acct ? inr(acct.wallet_balance_inr) : "—"}</div>
            <div className="flex justify-between text-[11px] opacity-85 mt-2"><span className="truncate">{acct?.upi_id ?? "—"}</span><span className="capitalize">KYC {acct?.kyc ?? "—"}</span></div>
          </div>
        )}

        {/* Missions */}
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="flex justify-between items-center mb-2">
            <div className="text-xs font-semibold text-[var(--pn-muted)] uppercase tracking-wider">Security missions</div>
            <div className="text-[11px] font-mono text-[var(--pn-muted)]">{doneCount}/{MISSIONS.length} flags</div>
          </div>
          <Link href="/demos" className="mb-2.5 flex items-center gap-2 rounded-xl px-3 py-2 text-[12px] border border-[#5eead4]/25 bg-[#5eead4]/[.05] hover:border-[#5eead4]/50">
            <span className="text-[#5eead4]">▶</span>
            <span className="flex-1">Watch all {MISSIONS.length} as recorded demos <span className="text-[var(--pn-muted)]">· no sign-in, no tokens</span></span>
          </Link>
          <div className="h-1 rounded-full bg-white/5 mb-3 overflow-hidden"><div className="h-full bg-gradient-to-r from-[#2dd4bf] to-[#7c3aed] transition-all" style={{ width: `${(doneCount / MISSIONS.length) * 100}%` }} /></div>
          <div className="pn-scroll overflow-auto flex flex-col gap-1.5 pr-1">
            {MISSIONS.map((m, n) => {
              const isOpen = openMission === m.id, ok = !!done[m.id];
              return (
                <div key={m.id} className={`rounded-xl border transition ${isOpen ? "border-[#5eead4]/40 bg-white/[.04]" : "border-[var(--pn-line)] bg-white/[.015]"}`}>
                  <button onClick={() => setOpenMission(isOpen ? null : m.id)} className="w-full text-left px-3 py-2.5 flex items-center gap-2.5">
                    <span className={`w-6 h-6 shrink-0 rounded-lg grid place-items-center text-[11px] font-bold ${ok ? "bg-[#2ee6a6]/20 text-[#2ee6a6]" : "bg-white/5 text-[var(--pn-muted)]"}`}>{ok ? "✓" : n + 1}</span>
                    <span className="flex-1 min-w-0 text-[13px] font-medium truncate">{m.title}</span>
                    <span className="flex gap-1">{m.layers.slice(0, 2).map((l) => <span key={l} className={`text-[9.5px] font-mono px-1.5 py-[1px] rounded border ${LAYER_CHIP[l]}`}>{l}</span>)}</span>
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-3 text-[12.5px]">
                      <p className="text-[#c9d0e6]">{m.goal}</p>
                      <ol className="mt-2 space-y-1.5">
                        {m.steps.map((s, k) => (
                          <li key={k} className="flex items-center gap-2">
                            <span className="text-[10px] font-mono text-[var(--pn-muted)] w-3">{k + 1}</span>
                            {s.prompt ? (
                              <button disabled={busy || locked} onClick={() => send(resolvePrompt(s.prompt!))}
                                className="flex-1 text-left rounded-lg px-2.5 py-1.5 bg-white/[.04] border border-[var(--pn-line)] hover:border-[#5eead4]/50 disabled:opacity-50">
                                <span className="text-[10.5px] text-[#5eead4] font-semibold mr-1">{s.label} ▸</span>
                                <span className="text-[#dfe4f5]">{resolvePrompt(s.prompt)}</span>
                              </button>
                            ) : s.sample ? (
                              <div className="flex-1 rounded-lg px-2.5 py-2 bg-white/[.04] border border-dashed border-[var(--pn-line)]">
                                <div className="text-[#dfe4f5]">📄 {s.label} <span className="font-mono text-[10.5px] text-[var(--pn-muted)]">{s.sample}</span></div>
                                <div className="mt-1.5 flex gap-1.5">
                                  <button disabled={busy || locked || role === "admin"} onClick={() => attachSample(s.sample!)}
                                    className="rounded-md px-2.5 py-1 text-[11.5px] font-semibold bg-[#14b8a6] text-[#04201c] hover:brightness-110 disabled:opacity-50">⬆ Attach it for me</button>
                                  <button onClick={() => saveSample(s.sample!)}
                                    className="rounded-md px-2.5 py-1 text-[11.5px] border border-[var(--pn-line)] hover:border-[#5eead4]/50">⬇ Save a copy</button>
                                </div>
                                {sampleMsg[s.sample] && <div className="mt-1 text-[11px] text-[var(--pn-muted)]">{sampleMsg[s.sample]}</div>}
                              </div>
                            ) : s.switchTo ? (
                              <button onClick={() => switchTo(s.switchTo!)} disabled={role === s.switchTo}
                                className="flex-1 text-left rounded-lg px-2.5 py-1.5 bg-[#22d3ee]/10 border border-[#22d3ee]/30 disabled:opacity-50">⇄ {s.label}{role === s.switchTo ? " (done)" : ""}</button>
                            ) : (
                              <button onClick={() => fileRef.current?.click()} className="flex-1 text-left rounded-lg px-2.5 py-1.5 bg-white/[.04] border border-[var(--pn-line)]">📎 {s.label}</button>
                            )}
                          </li>
                        ))}
                      </ol>
                      <details className="mt-2.5 group">
                        <summary className="cursor-pointer text-[11.5px] text-[var(--pn-muted)] hover:text-white">What this proves (interview notes)</summary>
                        <p className="mt-1.5 text-[12px] leading-relaxed text-[#b9c2dc]">{m.talk}</p>
                      </details>
                      {ok && <div className="mt-2 font-mono text-[11px] text-[#2ee6a6]">{m.flag}</div>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {doneCount > 0 && <button onClick={() => { saveDone({}); setDone({}); }} className="mt-2 text-[10.5px] text-[var(--pn-muted)] hover:text-white self-start">reset progress</button>}
        </div>
        {authErr && <Link href="/login" className="text-sm text-[#99f6e4] underline">Sign in to start →</Link>}
      </aside>

      {/* ---------- Chat ---------- */}
      <main className="flex-1 min-w-0 flex flex-col h-screen">
        <header className="flex items-center gap-3 px-5 md:px-8 py-3 border-b border-[var(--pn-line)]">
          <div className="relative"><KavachMark size={38} />
            <span className="pn-pulse absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-[var(--pn-ok)] border-2 border-[#070912]" /></div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold">{BRAND.assistant} <span className="text-[var(--pn-muted)] font-normal">· Kavach Assist</span></div>
            <div className="text-[11.5px] text-[var(--pn-muted)] flex gap-2 items-center flex-wrap">
              <span className="inline-flex items-center gap-1"><ShieldLayerMark size={12} /> ShieldLayer · 4 layers</span>
              {tainted && <span className="text-[#fcd34d]" title="This chat has read an uploaded file, so actions need your confirmation">· Rule of Two active</span>}
              <span className="hidden sm:inline font-mono text-[10.5px] opacity-80">· {modelName}</span>
            </div>
          </div>
          <span className={`hidden sm:inline text-[11px] font-mono px-2 py-1 rounded-md border ${role === "admin" ? "border-[#22d3ee]/40 text-[#67e8f9]" : "border-[var(--pn-line)] text-[var(--pn-muted)]"}`}>role: {role}</span>
          <button onClick={() => switchTo(role === "admin" ? "user" : "admin")} className="pn-chip rounded-lg px-3 py-1.5 text-xs">⇄ {role === "admin" ? "Customer" : "Admin"}</button>
          <QuotaChip quota={quota} hasKey={!!visitorKey} onClick={() => setKeyOpen(true)} />
          <button onClick={newChat} className="pn-chip rounded-lg px-3 py-1.5 text-xs">＋ New</button>
          <Link href="/console" className="pn-chip rounded-lg px-3 py-1.5 text-xs hidden md:inline-block">Console ↗</Link>
        </header>

        <div className="pn-scroll flex-1 overflow-auto px-4 md:px-8 py-6">
          <div className="max-w-3xl mx-auto flex flex-col gap-5">
            {msgs.length === 0 && (
              <div className="pn-fade-in pt-4 md:pt-10 text-center">
                <KavachMark size={64} className="mx-auto drop-shadow-[0_14px_34px_rgba(79,70,229,.45)]" />
                <h1 className="mt-5 text-3xl md:text-[38px] font-bold tracking-tight leading-tight">Hey {firstName}, <span className="pn-grad-text">how can I help?</span></h1>
                <p className="mt-3 text-[var(--pn-muted)] max-w-lg mx-auto text-[15px]">
                  Ask about payments, refunds or fraud, attach a document, or follow the missions on the left to see every security layer in action.
                </p>
                <div className="mt-7 grid grid-cols-1 md:grid-cols-3 gap-3 text-left">
                  {/* L1: 3-Stage Deterministic Funnel */}
                  <div className="pn-glass rounded-xl px-3.5 py-3 flex flex-col justify-between border border-[#5eead4]/30 bg-[#5eead4]/[0.04]">
                    <div>
                      <div className="flex items-center justify-between text-[11px] font-mono text-[#5eead4]">
                        <span>L1 · 3 STAGES</span>
                        <span className="text-[#5eead4]/70 text-[10px]">&lt; 2ms</span>
                      </div>
                      <div className="text-[13.5px] font-semibold mt-0.5">Deterministic Funnel</div>
                      <div className="text-[11px] text-[var(--pn-muted)] mt-0.5">Sequential sub-stage threat filter</div>
                    </div>
                    <div className="mt-2.5 pt-2 border-t border-white/10 flex flex-col gap-1.5 text-[10.5px] font-mono">
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#5eead4] shrink-0" />
                        <span className="text-[#5eead4] font-semibold">1A</span>
                        <span className="text-[var(--pn-muted)] truncate">Canonicalizer &amp; Unpack</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#5eead4] shrink-0" />
                        <span className="text-[#5eead4] font-semibold">1B</span>
                        <span className="text-[var(--pn-muted)] truncate">Aho-Corasick (61 sigs)</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#5eead4] shrink-0" />
                        <span className="text-[#5eead4] font-semibold">1C</span>
                        <span className="text-[var(--pn-muted)] truncate">Targeted Regex (22 rules)</span>
                      </div>
                    </div>
                  </div>

                  {/* L2: Quarantined Intent Extractor & Neutralizer */}
                  <div className="pn-glass rounded-xl px-3.5 py-3 flex flex-col justify-between border border-[#818cf8]/30 bg-[#818cf8]/[0.03]">
                    <div>
                      <div className="flex items-center justify-between text-[11px] font-mono text-[#818cf8]">
                        <span>L2 · INTENT EXTRACTOR</span>
                        <span className="text-[var(--pn-muted)] text-[10px]">~100ms</span>
                      </div>
                      <div className="text-[13.5px] font-semibold mt-0.5">Quarantined Intent Extractor</div>
                      <div className="text-[11px] text-[var(--pn-muted)] mt-0.5">Schema-enforced JSON &amp; neutralizer</div>
                    </div>
                    <div className="mt-2.5 pt-2 border-t border-white/10 flex flex-col gap-1.5 text-[11px] text-[var(--pn-muted)]">
                      <div className="flex items-center gap-1.5 font-mono text-[10.5px]">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#818cf8] shrink-0" />
                        <span className="text-[#818cf8] font-semibold">Zero tools</span>
                        <span className="truncate">Isolated extraction sandbox</span>
                      </div>
                      <div className="text-[10.5px]">
                        Extracts intents[], authority claim &amp; neutral summary (Gemini / Ollama / Heuristic).
                      </div>
                    </div>
                  </div>

                  {/* L3: Deterministic Policy & Symbolic Gate */}
                  <div className="pn-glass rounded-xl px-3.5 py-3 flex flex-col justify-between border border-[#a78bfa]/30 bg-[#a78bfa]/[0.03]">
                    <div>
                      <div className="flex items-center justify-between text-[11px] font-mono text-[#a78bfa]">
                        <span>L3 · SYMBOLIC GATE</span>
                        <span className="text-[var(--pn-muted)] text-[10px]">&lt; 1ms</span>
                      </div>
                      <div className="text-[13.5px] font-semibold mt-0.5">Deterministic Policy Gate</div>
                      <div className="text-[11px] text-[var(--pn-muted)] mt-0.5">100% pure deterministic code</div>
                    </div>
                    <div className="mt-2.5 pt-2 border-t border-white/10 flex flex-col gap-1.5 text-[11px] text-[var(--pn-muted)]">
                      <div className="flex items-center gap-1.5 font-mono text-[10.5px]">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#a78bfa] shrink-0" />
                        <span className="text-[#a78bfa] font-semibold">Zero AI / Zero Scores</span>
                      </div>
                      <div className="text-[10.5px]">
                        Authority spoofing checks (ASI01) + RBAC &amp; ABAC ownership + taint invariants.
                      </div>
                    </div>
                  </div>
                </div>
                <button onClick={() => { const m = MISSIONS.find((x) => !done[x.id]) ?? MISSIONS[0]; setOpenMission(m.id); const p = m.steps.find((s) => s.prompt)?.prompt; if (p) send(resolvePrompt(p)); }}
                  className="mt-6 rounded-xl px-5 py-2.5 font-semibold text-[14px] bg-gradient-to-r from-[#14b8a6] to-[#4f46e5] shadow-lg shadow-[#4f46e5]/30 hover:brightness-110">
                  ▸ {doneCount ? "Continue missions" : "Start mission 1"}
                </button>
              </div>
            )}

            {msgs.map((m, i) => m.role === "user" ? (
              <div key={i} className="pn-fade-in self-end max-w-[85%] md:max-w-[75%]">
                <div className="pn-bubble-user text-white rounded-2xl rounded-br-md px-4 py-2.5 text-[14.5px] leading-relaxed whitespace-pre-wrap break-words">{m.text}</div>
              </div>
            ) : m.role === "upload" && m.upload ? (
              <UploadCard key={i} u={m.upload} />
            ) : (
              <BotMessage key={i} m={m} open={openTrace === i}
                onToggle={() => setOpenTrace(openTrace === i ? null : i)}
                onConfirm={(token) => confirm(i, token)}
                onCancel={() => setMsgs((x) => x.map((y, k) => k === i ? { ...y, confirmed: "Cancelled. Nothing was changed." } : y))} />
            ))}

            {busy && live.length + 1 > 0 && msgs[msgs.length - 1]?.role === "user" && (
              <div className="self-start w-full flex gap-3 pn-fade-in">
                <KavachMark size={30} className="shrink-0 mt-0.5" />
                <div className="pn-bubble-bot rounded-2xl rounded-tl-md px-4 py-3 w-full max-w-[540px]" aria-live="polite">
                  <TurnProgress events={live} running startedAt={startedAt} />
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        {/* composer */}
        <div className="px-4 md:px-8 pb-5 pt-2">
          <div className="max-w-3xl mx-auto">
            {locked ? (
              <div className="pn-glass rounded-2xl p-4 border border-[#fcd34d]/30">
                <div className="font-semibold text-[14.5px]">You&apos;ve used your {quota?.limit} free requests 🎉</div>
                <p className="text-[12.5px] text-[var(--pn-muted)] mt-1 leading-relaxed">
                  {quota?.reason === "daily" ? "The live demo's daily budget is used up (it resets at midnight UTC). "
                    : quota?.reason === "network" ? "Your network has used its free requests. " : ""}
                  The live model costs real tokens, so each visitor gets a few. You can still see everything:
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link href="/demos" className="rounded-xl px-4 py-2 text-[13px] font-semibold bg-gradient-to-r from-[#14b8a6] to-[#4f46e5] hover:brightness-110">▶ Watch the recorded demos</Link>
                  <button onClick={() => setKeyOpen(true)} className="pn-chip rounded-xl px-4 py-2 text-[13px]">🔑 Use my own Gemini key</button>
                  <Link href="/playground" className="pn-chip rounded-xl px-4 py-2 text-[13px]">⌁ Attack lab (3-Layer Pipeline)</Link>
                </div>
              </div>
            ) : (
            <div className="pn-input pn-glass rounded-2xl flex items-end gap-2 p-2 transition">
              <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) attach(f); e.target.value = ""; }} />
              <button onClick={() => fileRef.current?.click()} disabled={busy || role === "admin"} title={role === "admin" ? "Uploads are for the customer profile" : "Attach a PDF, DOCX, TXT or MD file"}
                className="h-10 w-10 shrink-0 rounded-xl grid place-items-center text-[var(--pn-muted)] hover:text-white hover:bg-white/5 disabled:opacity-40" aria-label="Attach file">
                <svg width="19" height="19" viewBox="0 0 24 24" fill="none"><path d="M21 11.5l-8.5 8.5a5 5 0 01-7-7L14 4.5a3.3 3.3 0 014.7 4.7L10.2 17.7a1.7 1.7 0 01-2.4-2.4L15.5 7.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
              </button>
              <textarea ref={inputRef} value={input} rows={1} autoFocus onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder={`Message ${BRAND.assistant}…  (never type your UPI PIN or OTP)`}
                className="flex-1 resize-none bg-transparent outline-none px-2 py-2.5 text-[14.5px] placeholder:text-[var(--pn-muted)] max-h-40" />
              <button onClick={() => send()} disabled={busy || !input.trim()} aria-label="Send"
                className="h-10 w-10 rounded-xl grid place-items-center bg-gradient-to-br from-[#14b8a6] to-[#4f46e5] disabled:opacity-40 hover:brightness-110 transition shadow-lg shadow-[#4f46e5]/30">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M4 12l16-8-6 16-2.5-6.5L4 12z" fill="white" /></svg>
              </button>
            </div>
            )}
            <div className="text-center text-[10.5px] text-[var(--pn-muted)] mt-2">
              Messages, files and tool results are scanned (L1-L3). Every action is checked for where it came from (L4). Kavi can't move money.
            </div>
          </div>
        </div>
      </main>

      <KeyDialog open={keyOpen} onClose={() => { setKeyOpen(false); refreshQuota(); }} model={quota?.visitor_key_model} />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 pn-fade-in max-w-sm rounded-2xl p-4 bg-[#0d1424] border border-[#2ee6a6]/40 shadow-2xl shadow-black/50">
          <div className="text-[11px] uppercase tracking-[.16em] text-[#2ee6a6]">Mission complete</div>
          <div className="font-semibold mt-0.5">{toast.title}</div>
          <div className="font-mono text-[12px] text-[#2ee6a6] mt-1">{toast.flag}</div>
          <p className="text-[12px] text-[#b9c2dc] mt-1.5 leading-relaxed">{toast.talk}</p>
        </div>
      )}
    </div>
  );
}

/** "3 of 4 free left" on the hosted demo, or "your key" once a visitor key is set. */
function QuotaChip({ quota, hasKey, onClick }: { quota: DemoStatus | null; hasKey: boolean; onClick: () => void }) {
  if (!quota?.public && !hasKey) return null;
  const left = quota?.remaining ?? 0;
  const cls = hasKey ? "border-[#5eead4]/40 text-[#99f6e4]" : left > 0 ? "border-[var(--pn-line)] text-[var(--pn-muted)]" : "border-[#fcd34d]/40 text-[#fcd34d]";
  return (
    <button onClick={onClick} title="Free requests on the live demo, or use your own Gemini key"
      className={`hidden sm:inline text-[11px] font-mono px-2 py-1 rounded-md border hover:text-white ${cls}`}>
      {hasKey ? "🔑 your key" : `${left}/${quota?.limit} free`}
    </button>
  );
}
