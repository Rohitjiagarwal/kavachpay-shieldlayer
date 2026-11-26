"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/** A funnel decision (no `kind`) or an agent activity event (`kind: "agent"`). */
export type FeedItem = { id: string; kind?: "agent"; ts?: number | string; [k: string]: any };

export const isAgent = (x: FeedItem) => x.kind === "agent";
export const tsOf = (x: FeedItem) =>
  typeof x.ts === "number" ? x.ts * 1000 : x.ts ? Date.parse(String(x.ts)) : Date.now();

/** Live SSE feed from /api/events (server replays its last 200 items on connect). */
export function useFeed(max = 300) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [connected, setConnected] = useState(false);
  const paused = useRef(false);
  const buffer = useRef<FeedItem[]>([]);
  const [pausedState, setPausedState] = useState(false);

  useEffect(() => {
    const es = new EventSource(api.eventsUrl(), { withCredentials: true } as any);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data) as FeedItem;
      if (paused.current) { buffer.current.unshift(d); return; }
      setItems((r) => (r.some((x) => x.id === d.id) ? r : [d, ...r].slice(0, max)));
    };
    return () => es.close();
  }, [max]);

  const setPaused = (p: boolean) => {
    paused.current = p;
    setPausedState(p);
    if (!p && buffer.current.length) {
      const b = buffer.current; buffer.current = [];
      setItems((r) => [...b, ...r].slice(0, max));
    }
  };
  return { items, connected, paused: pausedState, setPaused, clear: () => setItems([]) };
}

export function timeAgo(ms: number) {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}
