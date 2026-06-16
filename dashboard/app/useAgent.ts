"use client";

import { useEffect, useState } from "react";

export function useAgent<T>(path: string, initial: T, ms = 5000): [T, boolean] {
  const [data, setData] = useState<T>(initial);
  const [live, setLive] = useState(false);
  useEffect(() => {
    const tick = async () => {
      try {
        const r = await fetch(`/agent${path}`);
        if (!r.ok) throw new Error(String(r.status));
        setData(await r.json()); setLive(true);
      } catch { setLive(false); }
    };
    tick();
    const id = setInterval(tick, ms);
    return () => clearInterval(id);
  }, [path, ms]);
  return [data, live];
}

export function useAgentText(path: string, ms = 8000): [string, boolean] {
  const [data, setData] = useState("");
  const [live, setLive] = useState(false);
  useEffect(() => {
    const tick = async () => {
      try {
        const r = await fetch(`/agent${path}`);
        if (!r.ok) throw new Error(String(r.status));
        setData(await r.text()); setLive(true);
      } catch { setLive(false); }
    };
    tick();
    const id = setInterval(tick, ms);
    return () => clearInterval(id);
  }, [path, ms]);
  return [data, live];
}

export const fmt = (n: number) =>
  n.toLocaleString("en-US", { maximumFractionDigits: 2 });

/** A real on-chain hash (vs a paper-mode id like "paper-3"). */
export const isRealTx = (h?: string | null): h is string =>
  !!h && /^0x[0-9a-fA-F]{6,}$/.test(h);

/** Shorten a hash for display: 0x12ab34…cd9f */
export const shortTx = (h: string) =>
  h.length > 14 ? `${h.slice(0, 8)}…${h.slice(-4)}` : h;

/** A simulated (paper) fill id, e.g. "paper-3" / "paper-close-7". */
export const isSimTx = (h?: string | null): h is string =>
  !!h && /^paper(-close)?-\d+$/.test(h);

/** Compact duration from seconds: "45s", "12m", "3h 8m", "2d 4h". */
export const dur = (s?: number | null) => {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
};
