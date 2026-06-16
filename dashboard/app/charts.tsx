"use client";

import { useState, type MouseEvent } from "react";
import { fmt } from "./useAgent";

export type Pt = { t: number; v: number };

/* Equity chart — hi-fidelity: gridlines, y-axis ticks, time axis, optional
   baseline (deposit) reference, last-value marker, and a hover crosshair +
   tooltip. Non-zero baseline (variation is the signal). */
export function EquityChart({ series, title, sub, baseline }:
  { series: Pt[]; title: string; sub?: string; baseline?: number }) {
  const [hi, setHi] = useState<number | null>(null);
  if (!series || series.length < 2) {
    return (
      <div className="chartbox">
        <div className="chart-head"><span className="chart-title">{title}</span></div>
        <div className="chart-empty">accumulating equity history…</div>
      </div>
    );
  }
  const W = 600, H = 168, padT = 10, padB = 18;
  const vs = series.map((p) => p.v);
  let min = Math.min(...vs), max = Math.max(...vs);
  if (baseline != null) { min = Math.min(min, baseline); max = Math.max(max, baseline); }
  const span = (max - min) || 1;
  min -= span * 0.10; max += span * 0.10;
  const rng = max - min || 1;
  const x = (i: number) => (i / (series.length - 1)) * W;
  const y = (v: number) => padT + (1 - (v - min) / rng) * (H - padT - padB);
  const line = series.map((p, i) => `${x(i)},${y(p.v)}`).join(" ");
  const up = series[series.length - 1].v >= series[0].v;
  const col = up ? "var(--profit)" : "var(--loss)";
  const ticks = [max - rng * 0.06, (max + min) / 2, min + rng * 0.06];
  const last = series[series.length - 1];
  const hov = hi != null ? series[hi] : null;
  const t = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const idx = Math.round(((e.clientX - r.left) / r.width) * (series.length - 1));
    setHi(Math.max(0, Math.min(series.length - 1, idx)));
  };
  return (
    <div className="chartbox">
      <div className="chart-head">
        <span className="chart-title">{title}</span>
        {sub && <span className="chart-sub">{sub}</span>}
      </div>
      <div className="chart-area" onMouseMove={onMove} onMouseLeave={() => setHi(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 168, display: "block" }}>
          <defs>
            <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={up ? "rgba(24,200,120,0.22)" : "rgba(255,77,77,0.20)"} />
              <stop offset="100%" stopColor="rgba(0,0,0,0)" />
            </linearGradient>
          </defs>
          {ticks.map((tv, i) => (
            <line key={i} x1="0" x2={W} y1={y(tv)} y2={y(tv)} stroke="var(--border-soft)"
              strokeWidth="1" vectorEffect="non-scaling-stroke" opacity="0.45" />
          ))}
          {baseline != null && (
            <line x1="0" x2={W} y1={y(baseline)} y2={y(baseline)} stroke="var(--text-muted)"
              strokeWidth="1" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" opacity="0.7" />
          )}
          <polygon points={`0,${H - padB} ${line} ${W},${H - padB}`} fill="url(#eqfill)" />
          <polyline points={line} fill="none" stroke={col} strokeWidth={2} vectorEffect="non-scaling-stroke" />
          <circle cx={x(series.length - 1)} cy={y(last.v)} r="3.2" fill={col} />
          {hov && (<>
            <line x1={x(hi!)} x2={x(hi!)} y1={padT} y2={H - padB} stroke="var(--text-muted)" strokeWidth="1" vectorEffect="non-scaling-stroke" opacity="0.7" />
            <circle cx={x(hi!)} cy={y(hov.v)} r="3.4" fill="var(--text-primary)" />
          </>)}
        </svg>
        {ticks.map((tv, i) => (
          <span key={i} className="ylabel" style={{ top: `${(y(tv) / H) * 100}%` }}>${fmt(tv)}</span>
        ))}
        {baseline != null && <span className="baseline-tag" style={{ top: `${(y(baseline) / H) * 100}%` }}>deposit</span>}
        <span className="xlabel xstart">{t(series[0].t)}</span>
        <span className="xlabel xend">{t(last.t)}</span>
        {hov && (
          <div className="chart-tip" style={{ left: `${(x(hi!) / W) * 100}%` }}>
            <b>${fmt(hov.v)}</b><span>{t(hov.t)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

/* Tiny inline trend line for KPI cards — no axes, sign-colored. */
export function Sparkline({ data, w = 96, h = 26 }: { data: number[]; w?: number; h?: number }) {
  if (!data || data.length < 2) return <svg width={w} height={h} aria-hidden="true" />;
  const min = Math.min(...data), max = Math.max(...data), rng = (max - min) || 1;
  const x = (i: number) => (i / (data.length - 1)) * w;
  const y = (v: number) => h - 2 - ((v - min) / rng) * (h - 4);
  const pts = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  const col = up ? "var(--profit)" : "var(--loss)";
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={col} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(data.length - 1)} cy={y(data[data.length - 1])} r="1.8" fill={col} />
    </svg>
  );
}

/* Capital allocation bar — spot vs perp split, and long vs short within. */
export function BookBar({ spot, perpLong, perpShort }:
  { spot: number; perpLong: number; perpShort: number }) {
  const total = Math.max(1e-9, spot + perpLong + perpShort);
  const seg = (n: number) => `${(n / total) * 100}%`;
  return (
    <div className="bookbar-wrap">
      <div className="bookbar">
        {spot > 0 && <div className="seg spot" style={{ width: seg(spot) }} title={`Spot long · ${spot}`} />}
        {perpLong > 0 && <div className="seg plong" style={{ width: seg(perpLong) }} title={`Perp long · ${perpLong}`} />}
        {perpShort > 0 && <div className="seg pshort" style={{ width: seg(perpShort) }} title={`Perp short · ${perpShort}`} />}
        {spot + perpLong + perpShort === 0 && <div className="seg empty" style={{ width: "100%" }} />}
      </div>
      <div className="bookbar-key">
        <span><i className="k spot" /> Spot {spot}</span>
        <span><i className="k plong" /> Perp L {perpLong}</span>
        <span><i className="k pshort" /> Perp S {perpShort}</span>
      </div>
    </div>
  );
}

/* Ranked horizontal bars from zero — for P/L attribution. */
export function AttributionBars({ rows, empty }: { rows: { label: string; net: number }[]; empty?: string }) {
  const data = rows.filter((r) => r.label !== "unknown").sort((a, b) => b.net - a.net);
  if (data.length === 0) return <div className="chart-empty">{empty ?? "no attribution yet"}</div>;
  const maxAbs = Math.max(1e-6, ...data.map((r) => Math.abs(r.net)));
  return (
    <div className="bars">
      {data.map((r) => {
        const w = Math.max(2, (Math.abs(r.net) / maxAbs) * 100);
        const pos = r.net >= 0;
        return (
          <div className="bar-row" key={r.label}>
            <span className="bar-label">{r.label.replace(/_/g, " ")}</span>
            <div className="bar-track">
              <div className={pos ? "bar pos" : "bar neg"} style={{ width: `${w}%` }} />
            </div>
            <span className={pos ? "bar-val pos" : "bar-val neg"}>{pos ? "+" : ""}{fmt(r.net)}</span>
          </div>
        );
      })}
    </div>
  );
}
