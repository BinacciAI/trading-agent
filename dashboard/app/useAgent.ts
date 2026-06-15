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
