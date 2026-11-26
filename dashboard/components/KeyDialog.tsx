"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { getKey, setKey } from "@/lib/byok";

/** Bring-your-own-key dialog. The key stays in this tab (sessionStorage) and is
 *  sent only as a request header; the server uses it for that request and forgets it. */
export default function KeyDialog({ open, onClose, model }: { open: boolean; onClose: () => void; model?: string }) {
  const [val, setVal] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const saved = typeof window !== "undefined" ? getKey() : null;

  useEffect(() => { if (open) { setVal(""); setMsg(null); } }, [open]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, onClose]);
  if (!open) return null;

  async function check(save: boolean) {
    const k = val.trim();
    if (!/^[A-Za-z0-9_-]{30,64}$/.test(k)) { setMsg({ ok: false, text: "That doesn't look like a Gemini API key (it usually starts with AIza)." }); return; }
    setBusy(true);
    const previous = getKey();
    setKey(k); // the check request carries it as X-Gemini-Key
    try {
      const r = await api.checkKey();
      setMsg({ ok: r.ok, text: r.message });
      if (!r.ok || !save) setKey(previous);
      if (r.ok && save) setTimeout(onClose, 700);
    } catch (e: any) {
      setKey(previous);
      setMsg({ ok: false, text: String(e?.message || e) });
    }
    setBusy(false);
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="key-title" onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl p-5 bg-[#0d1424] border border-[var(--pn-line)] shadow-2xl shadow-black/60 pn-fade-in">
        <div id="key-title" className="font-semibold text-[16px]">🔑 Use your own Gemini key</div>
        <p className="text-[12.5px] text-[var(--pn-muted)] mt-1.5 leading-relaxed">
          Unlimited messages, billed to your own Google AI Studio key{model ? <> (model <span className="font-mono">{model}</span>)</> : null}.
          Get a free key at{" "}
          <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" className="text-[#99f6e4] underline">aistudio.google.com/apikey</a>.
        </p>
        <ul className="mt-3 space-y-1 text-[11.5px] text-[#b9c2dc]">
          <li>• Stored only in this browser tab. Closing the tab forgets it.</li>
          <li>• Sent as a header with your requests, used for that request, never saved or logged on the server.</li>
          <li>• Used for both the chat reply and Layer-2 intent extraction.</li>
        </ul>
        <input type="password" autoComplete="off" spellCheck={false} value={val} onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") check(true); }}
          placeholder={saved ? "A key is set for this tab. Paste a new one to replace it" : "AIza…"}
          className="mt-4 w-full rounded-xl px-3 py-2.5 bg-white/[.04] border border-[var(--pn-line)] outline-none focus:border-[#5eead4]/60 font-mono text-[13px]" />
        {msg && <div className={`mt-2 text-[12px] ${msg.ok ? "text-[var(--pn-ok)]" : "text-[var(--pn-bad)]"}`}>{msg.text}</div>}
        <div className="mt-4 flex flex-wrap gap-2 justify-end">
          {saved && <button onClick={() => { setKey(null); setMsg({ ok: true, text: "Key removed from this tab." }); }} className="mr-auto text-[12px] text-[var(--pn-muted)] hover:text-white">Remove saved key</button>}
          <button onClick={onClose} className="pn-chip rounded-lg px-3.5 py-1.5 text-[13px]">Close</button>
          <button disabled={busy || !val.trim()} onClick={() => check(true)}
            className="rounded-lg px-3.5 py-1.5 text-[13px] font-semibold bg-gradient-to-r from-[#14b8a6] to-[#4f46e5] disabled:opacity-40">
            {busy ? "Checking…" : "Check & use key"}</button>
        </div>
      </div>
    </div>
  );
}
