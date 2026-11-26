"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, type DemoStatus } from "@/lib/api";
import { BRAND, KavachMark, ShieldLayerMark } from "@/components/Brand";

const LAYERS = [
  ["L1", "Deterministic Funnel", "1A Normalizer · 1B Aho-Corasick · 1C Regex, < 2 ms"],
  ["L2", "Intent Extractor", "Quarantined JSON extraction & neutralizer, ~100 ms"],
  ["L3", "Deterministic Policy Gate", "Pure deterministic RBAC/ABAC & authority gate, < 1 ms"],
];

export default function Login() {
  const [profiles, setProfiles] = useState<any[]>([]);
  const [waking, setWaking] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [demo, setDemo] = useState<DemoStatus | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = (attempt = 0) => {
      api.customers()
        .then((p) => { if (!cancelled) { setProfiles(p); setWaking(false); setErr(""); } })
        .catch((e) => {
          if (cancelled) return;
          if (attempt < 6) { timer = setTimeout(() => load(attempt + 1), 5000); }
          else { setWaking(false); setErr(String(e)); }
        });
      api.demoStatus().then((d) => { if (!cancelled) setDemo(d); }).catch(() => {});
    };
    load(0);
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, []);

  async function pick(p: any) {
    setBusy(p.id);
    try {
      await api.login(p.id);
      router.push(p.role === "admin" ? "/console" : "/chat");
    } catch (e) { setErr(String(e)); setBusy(null); }
  }

  return (
    <div className="pn-root min-h-screen grid place-items-center p-4">
      <div className="w-full max-w-3xl pn-fade-in">
        <div className="text-center mb-8">
          <KavachMark size={64} className="mx-auto drop-shadow-[0_12px_30px_rgba(79,70,229,.45)]" />
          <h1 className="mt-4 text-4xl font-bold tracking-tight">Kavach<span className="pn-grad-text">Pay</span></h1>
          <p className="text-[var(--pn-muted)] mt-1.5 text-[15px]">{BRAND.tagline}</p>
        </div>

        {waking && profiles.length === 0 && !err && (
          <p className="text-[var(--pn-muted)] text-xs text-center mb-3">
            Waking up the free backend server (~30s)… You can watch the Recorded Demos below right away.
          </p>
        )}
        {err && <p className="text-[var(--pn-bad)] text-sm text-center mb-3">API not reachable: {err}</p>}
        <Link href="/demos" className="mb-3 flex items-center gap-3 rounded-2xl px-4 py-3 border border-[#5eead4]/30 bg-[#5eead4]/[.06] hover:border-[#5eead4]/60 transition">
          <span className="w-9 h-9 rounded-xl grid place-items-center bg-[#5eead4]/15 text-[#5eead4]">▶</span>
          <span className="flex-1">
            <span className="block font-semibold text-[14px]">Short on time? Watch the recorded demos</span>
            <span className="block text-[12px] text-[var(--pn-muted)]">All 8 attacks replayed step by step. No sign-in, no tokens.</span>
          </span>
          <span className="text-[var(--pn-muted)]">→</span>
        </Link>
        <div className="grid sm:grid-cols-2 gap-3">
          {profiles.map((p) => {
            const admin = p.role === "admin";
            return (
              <button key={p.id} onClick={() => pick(p)} disabled={busy !== null}
                className="pn-glass pn-chip rounded-2xl p-5 text-left flex flex-col gap-3 disabled:opacity-60">
                <div className="flex items-center gap-3">
                  {admin ? (
                    <div className="w-11 h-11 rounded-xl grid place-items-center bg-[#06151a] border border-[#22d3ee]/40"><ShieldLayerMark size={26} /></div>
                  ) : (
                    <div className="w-11 h-11 rounded-xl grid place-items-center text-sm font-bold bg-gradient-to-br from-[#2dd4bf]/70 to-[#4f46e5]/80">
                      {p.name.split(" ").map((x: string) => x[0]).join("")}
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold">{p.name}</div>
                    <div className="text-[11px] uppercase tracking-[.16em] text-[var(--pn-muted)]">{p.title}</div>
                  </div>
                  <span className="text-[var(--pn-muted)]">{busy === p.id ? "…" : "→"}</span>
                </div>
                <p className="text-[13px] text-[#c9d0e6] leading-relaxed">{p.blurb}</p>
                <div className="text-[11px] font-mono text-[var(--pn-muted)]">{admin ? "opens the security console" : "opens the chat + missions"}</div>
              </button>
            );
          })}
        </div>

        <div className="mt-8 pn-glass rounded-2xl p-4">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[.16em] text-[var(--pn-muted)] mb-3">
            <ShieldLayerMark size={16} /> Protected by ShieldLayer · 3 layers
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {LAYERS.map(([k, n, d]) => (
              <div key={k} className="rounded-xl bg-white/[.03] border border-[var(--pn-line)] px-3 py-2.5">
                <div className="text-[11px] font-mono text-[#5eead4]">{k}</div>
                <div className="text-[13px] font-semibold">{n}</div>
                <div className="text-[11px] text-[var(--pn-muted)]">{d}</div>
              </div>
            ))}
          </div>
        </div>
        <p className="text-center text-[11px] text-[var(--pn-muted)] mt-4">
          Fictional demo app. No real money, no real accounts.
          {demo?.public && <> Live demo: {demo.limit} free requests per visitor, or bring your own Gemini key.</>}
        </p>
      </div>
    </div>
  );
}
