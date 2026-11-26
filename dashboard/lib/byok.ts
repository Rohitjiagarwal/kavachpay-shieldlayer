"use client";
/**
 * The visitor's own Gemini key ("bring your own key").
 * Kept in sessionStorage only: it disappears when the tab closes, is sent as the
 * X-Gemini-Key header with model-backed requests, and is never stored server side.
 */
import { useEffect, useState } from "react";

const K = "kavach-gemini-key";
const EVT = "kavach-key-change";

export function getKey(): string | null {
  try { return sessionStorage.getItem(K); } catch { return null; }
}

export function setKey(k: string | null) {
  try { if (k) sessionStorage.setItem(K, k.trim()); else sessionStorage.removeItem(K); } catch { /* storage blocked */ }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVT));
}

export function keyHeader(): Record<string, string> {
  const k = getKey();
  return k ? { "X-Gemini-Key": k } : {};
}

export function useKey(): string | null {
  const [k, setK] = useState<string | null>(null);
  useEffect(() => {
    const read = () => setK(getKey());
    read();
    window.addEventListener(EVT, read);
    return () => window.removeEventListener(EVT, read);
  }, []);
  return k;
}
