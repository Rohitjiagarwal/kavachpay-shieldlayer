import { keyHeader } from "@/lib/byok";

/** Same-origin in the single-container build (the API serves the dashboard). */
export const API = process.env.NEXT_PUBLIC_SAME_ORIGIN === "1" ? "" : (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080");
/** Optional, local only. Never bake a real token into a public build. */
const ADMIN_TOKEN = process.env.NEXT_PUBLIC_ADMIN_TOKEN || "";

/** Thrown for any non-2xx. `quota` is set when the free-request budget is used up. */
export class ApiError extends Error {
  status: number;
  quota: boolean;
  detail: any;
  constructor(status: number, body: string) {
    let detail: any = body;
    try { detail = JSON.parse(body).detail ?? body; } catch { /* plain text */ }
    const msg = typeof detail === "string" ? detail : detail?.message || JSON.stringify(detail);
    super(`${status} ${msg}`);
    this.status = status;
    this.detail = detail;
    this.quota = status === 429 && detail?.code === "quota";
  }
}

async function req(path: string, opts: RequestInit = {}) {
  const r = await fetch(`${API}${path}`, {
    credentials: "include",
    ...opts,
    headers: { "Content-Type": "application/json", ...keyHeader(), ...(opts.headers || {}) },
  });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return r.json();
}

/** Free-request budget of the hosted demo (public=false on a local install). */
export type DemoStatus = {
  public: boolean; limit: number; used: number; remaining: number | null; reason: string;
  visitor_key_model: string;
};

/** One progress event from /api/chat/stream (see app/pipeline.py). */
export type TurnEvent = {
  type: "step" | "layer" | "tool" | "gate" | "model" | "final" | "error";
  id?: string;
  status?: string;
  label?: string;
  detail?: string;
  ms?: number;
  t?: number;
  phase?: string;
  tokens?: number;
  message?: string;
  [k: string]: any;
};

/** POST a chat message and call onEvent for every NDJSON line as it arrives. */
async function chatStream(message: string, onEvent: (e: TurnEvent) => void): Promise<TurnEvent> {
  const r = await fetch(`${API}/api/chat/stream`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...keyHeader() },
    body: JSON.stringify({ message }),
  });
  if (r.status === 404) {
    // older backend without the streaming endpoint: plain request, no live steps
    onEvent({
      type: "step", id: "legacy", status: "warn", label: "Live steps unavailable",
      detail: "the API server is an older build without /api/chat/stream. Restart uvicorn to see each step. Waiting for the full reply…",
    });
    return { type: "final", ...(await req("/api/chat", { method: "POST", body: JSON.stringify({ message }) })) };
  }
  if (!r.ok || !r.body) throw new ApiError(r.status, await r.text());
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let final: TurnEvent | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const ev = JSON.parse(line) as TurnEvent;
      if (ev.type === "final") final = ev;
      if (ev.type === "error") throw new Error(ev.message || "stream error");
      onEvent(ev);
    }
  }
  if (!final) throw new Error("stream ended without a reply");
  return final;
}

/** Attach a file in chat; onEvent gets parse / per-chunk scan / final events. */
async function uploadStream(file: File, onEvent: (e: any) => void): Promise<any> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API}/api/chat/upload`, { method: "POST", credentials: "include", body: fd, headers: keyHeader() });
  if (!r.ok || !r.body) throw new ApiError(r.status, await r.text());
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "", final: any = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const ev = JSON.parse(line);
      if (ev.type === "error") throw new Error(ev.message);
      if (ev.type === "final") final = ev;
      onEvent(ev);
    }
  }
  if (!final) throw new Error("upload ended without a result");
  return final;
}

export const api = {
  uploadStream,
  sampleUrl: (name: string) => `${API}/api/samples/${name}`,
  customers: () => req("/api/customers"),
  login: (customer_id: number) =>
    req("/api/login", { method: "POST", body: JSON.stringify({ customer_id }) }),
  chat: (message: string) =>
    req("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
  chatStream,
  confirm: (confirm_token: string) =>
    req("/api/chat/confirm", { method: "POST", body: JSON.stringify({ confirm_token }) }),
  reset: () => req("/api/chat/reset", { method: "POST" }),
  me: () => req("/api/me"),
  health: () => req("/health"),
  stats: () => req("/api/stats"),
  shieldInfo: () => req("/api/shield/info"),
  playground: (text: string, source: string) =>
    req("/api/playground", { method: "POST", body: JSON.stringify({ text, source }) }),
  scorecard: () => req("/api/scorecard"),
  quarantine: () =>
    req("/api/quarantine", { headers: ADMIN_TOKEN ? { "X-Admin-Token": ADMIN_TOKEN } : {} }),
  demoStatus: (): Promise<DemoStatus> => req("/api/demo/status"),
  checkKey: (): Promise<{ ok: boolean; message: string }> => req("/api/byok/check", { method: "POST" }),
  documents: () => req("/api/documents"),
  eventsUrl: () => `${API}/api/events`,
};
