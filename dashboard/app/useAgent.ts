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
