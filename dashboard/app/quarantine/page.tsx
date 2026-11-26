"use client";
import { useEffect, useMemo, useState } from "react";
import Shell from "@/components/Shell";
import { LayerTag, Panel } from "@/components/VerdictBadge";
import { api } from "@/lib/api";

export default function Quarantine() {
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [hiddenOnly, setHiddenOnly] = useState(false);
  const [open, setOpen] = useState<number | null>(null);

  const load = () => api.quarantine().then((r) => { setRows(r); setErr(""); }).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const shown = useMemo(() => rows.filter((r) =>
    (!hiddenOnly || r.hidden_text) && (!q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()))), [rows, q, hiddenOnly]);
  const docs = useMemo(() => {
    const m = new Map<string, any[]>();
    for (const r of shown) m.set(r.doc_id, [...(m.get(r.doc_id) ?? []), r]);
    return [...m.entries()];
  }, [shown]);
  const count = (k: string) => rows.reduce<Record<string, number>>((a, r) => ({ ...a, [r[k] ?? "—"]: (a[r[k] ?? "—"] ?? 0) + 1 }), {});

  return (
    <Shell title="Quarantine" subtitle="Document chunks the funnel flagged during ingestion. They never reached the vector store, so no retrieval can surface them to the agent. Docs fail closed."
      actions={<button className="sl-btn" onClick={load}>↻ Refresh</button>}>
      {err && <div className="sl-panel border-block/40 p-3 mb-4 text-block text-[13px]">{err}. Sign in first: you see the files your browser uploaded (the admin profile on a local install sees all).</div>}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <Tile k="Chunks held" v={rows.length} />
        <Tile k="Documents affected" v={new Set(rows.map((r) => r.doc_id)).size} />
        <Tile k="Hidden-text tricks" v={rows.filter((r) => r.hidden_text).length} />
        <Tile k="By layer" v={Object.entries(count("layer")).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"} small />
      </div>
      <Panel bodyClass="p-0">
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-line text-[12px]">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search chunk text, reason, OWASP id, doc…" className="sl-input px-3 py-1.5 text-[12.5px] flex-1 min-w-[220px]" />
          <label className="flex items-center gap-2 text-muted cursor-pointer select-none">
            <input type="checkbox" checked={hiddenOnly} onChange={(e) => setHiddenOnly(e.target.checked)} className="accent-[var(--brand)]" /> hidden text only
          </label>
          <span className="font-mono text-muted">{shown.length} shown</span>
        </div>
        {shown.length === 0 && !err && <div className="p-6 text-muted text-[13px]">Nothing quarantined. Upload a poisoned PDF from the customer chat to see a chunk land here.</div>}
        {docs.map(([doc, items]) => (
          <div key={doc} className="border-b border-line last:border-0">
            <div className="px-4 py-2 bg-panel2/50 text-[11.5px] flex justify-between"><span className="font-mono">doc {doc}</span><span className="text-muted">{items.length} chunk(s) held</span></div>
            {items.map((r) => (
              <div key={r.id} className="px-4 py-3 border-t border-line/60">
                <div className="flex flex-wrap items-center gap-2 text-[11.5px] mb-2">
                  <span className="font-mono font-medium text-block">{r.owasp}</span>
                  <LayerTag layer={r.layer} />
                  {r.score != null && <span className="font-mono text-muted">score {Number(r.score).toFixed(3)}</span>}
                  {r.hidden_text && <span className="rounded border border-warn/40 text-warn px-1.5 py-0.5 font-mono text-[10.5px]">hidden text</span>}
                  <span className="text-muted truncate flex-1">{r.reason}</span>
                  <button className="text-brand" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "collapse" : "inspect"}</button>
                </div>
                <pre className={`text-[12px] font-mono whitespace-pre-wrap break-words rounded-md border border-block/20 bg-block/[0.04] p-3 text-ink/85 ${open === r.id ? "" : "max-h-[84px] overflow-hidden"}`}>{r.text}</pre>
              </div>
            ))}
          </div>
        ))}
      </Panel>
    </Shell>
  );
}

function Tile({ k, v, small }: { k: string; v: any; small?: boolean }) {
  return (
    <div className="sl-panel px-4 py-3">
      <div className="text-[10.5px] uppercase tracking-[.14em] text-muted">{k}</div>
      <div className={`${small ? "text-[13px] font-mono mt-2" : "text-[24px] font-semibold"} tabular-nums`}>{v}</div>
    </div>
  );
}
