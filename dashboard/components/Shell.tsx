"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ShieldLayerMark } from "@/components/Brand";

const NAV: { group: string; items: [string, string, string][] }[] = [
  { group: "Monitor", items: [["/console", "Overview", "◎"], ["/live", "Live activity", "≋"]] },
  { group: "Investigate", items: [["/playground", "Attack lab", "⌁"], ["/quarantine", "Quarantine", "▣"]] },
  { group: "Assess", items: [["/scorecard", "Scorecard", "▤"], ["/demos", "Recorded demos", "▶"]] },
];

export default function Shell({ children, title, subtitle, actions }: {
  children: React.ReactNode; title?: string; subtitle?: string; actions?: React.ReactNode;
}) {
  const path = usePathname();
  const [stats, setStats] = useState<any>(null);
  const [info, setInfo] = useState<any>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [clock, setClock] = useState("");

  useEffect(() => {
    const pull = () => api.stats().then((s) => { setStats(s); setOnline(true); }).catch(() => setOnline(false));
    pull();
    api.shieldInfo().then(setInfo).catch(() => {});
    const t = setInterval(pull, 3000);
    const c = setInterval(() => setClock(new Date().toISOString().slice(11, 19) + " UTC"), 1000);
    return () => { clearInterval(t); clearInterval(c); };
  }, []);

  return (
    <div className="sl-backdrop min-h-screen grid grid-cols-1 md:grid-cols-[232px_1fr] text-ink">
      <aside className="hidden md:flex flex-col border-r border-line bg-panel/80 backdrop-blur sticky top-0 h-screen">
        <div className="px-4 pt-5 pb-4 border-b border-line">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg grid place-items-center bg-brand/10 border border-brand/40"><ShieldLayerMark size={24} /></div>
            <div>
              <div className="font-semibold tracking-tight leading-tight">ShieldLayer</div>
              <div className="text-[10.5px] text-muted uppercase tracking-[.16em]">Agent security console</div>
            </div>
          </div>
        </div>
        <nav className="flex-1 overflow-auto sl-scroll px-2 py-3 space-y-4">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="px-2 mb-1 text-[10px] uppercase tracking-[.18em] text-muted/70">{g.group}</div>
              {g.items.map(([href, label, glyph]) => {
                const on = path === href;
                return (
                  <Link key={href} href={href}
                    className={`relative flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[13px] transition ${
                      on ? "bg-brand/10 text-ink" : "text-muted hover:text-ink hover:bg-panel2"}`}>
                    {on && <span className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded bg-brand" />}
                    <span className={`w-4 text-center font-mono ${on ? "text-brand" : ""}`}>{glyph}</span>
                    {label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="p-3 border-t border-line space-y-2">
          <div className="rounded-md border border-line bg-bg/60 p-2.5 text-[11px] space-y-1">
            <Posture k="Pipeline" v="3-Layer Zero-Judge" />
            <Posture k="Layer 2" v={info?.layer2 ?? "Intent Extractor"} />
            <Posture k="Layer 3" v="Symbolic Policy Gate" />
          </div>
          <Link href="/chat" className="sl-btn w-full justify-center text-[12px]">Open KavachPay chat ↗</Link>
          <Link href="/login" className="block text-center text-[11px] text-muted hover:text-ink">Switch profile</Link>
        </div>
      </aside>

      <div className="flex flex-col min-w-0">
        <header className="sticky top-0 z-10 border-b border-line bg-bg/85 backdrop-blur px-4 md:px-6 h-11 flex items-center gap-4 text-[11.5px] text-muted overflow-x-auto sl-scroll">
          <span className="flex items-center gap-1.5 shrink-0">
            {online ? <span className="sl-live-dot" /> : <span className="w-[7px] h-[7px] rounded-full bg-block" />}
            <span className={online ? "text-ok" : "text-block"}>{online === null ? "connecting" : online ? "API online" : "API offline"}</span>
          </span>
          <Sep />
          <Stat k="decisions" v={stats?.checked} />
          <Stat k="blocked" v={stats?.blocked} tone="text-block" />
          <Stat k="L1 funnel" v={stats?.blocked_layer1 ?? stats?.blocked_regex} />
          <Stat k="L2 intent" v={stats?.blocked_layer2 ?? stats?.blocked_classifier} />
          <Stat k="L3 policy" v={stats?.blocked_layer3 ?? stats?.blocked_judge} />
          <Stat k="L4 origin" v={stats?.blocked_provenance} />
          <span className="flex-1" />
          <span className="font-mono shrink-0 text-muted/80">{clock}</span>
        </header>

        <main className="p-4 md:p-6 min-w-0">
          {(title || actions) && (
            <div className="flex flex-wrap items-end justify-between gap-3 mb-5">
              <div>
                <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
                {subtitle && <p className="text-muted text-[13px] mt-0.5 max-w-3xl">{subtitle}</p>}
              </div>
              {actions && <div className="flex items-center gap-2">{actions}</div>}
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}

function Posture({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted">{k}</span>
      <span className="font-mono text-ink truncate max-w-[130px]" title={v}>{v}</span>
    </div>
  );
}
function Stat({ k, v, tone = "text-ink" }: { k: string; v: any; tone?: string }) {
  return <span className="shrink-0">{k} <b className={`font-mono font-medium ${tone}`}>{v ?? "–"}</b></span>;
}
function Sep() { return <span className="w-px h-4 bg-line shrink-0" />; }
