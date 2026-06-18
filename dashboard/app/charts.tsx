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

/* Drawdown from running peak — red area under the zero line. */
export function DrawdownArea({ series, title }: { series: Pt[]; title: string }) {
  if (!series || series.length < 2) {
    return (<div className="chartbox"><div className="chart-head"><span className="chart-title">{title}</span></div>
      <div className="chart-empty">accumulating drawdown…</div></div>);
  }
  let peak = -Infinity;
  const dd = series.map((p) => { peak = Math.max(peak, p.v); return peak > 0 ? ((p.v - peak) / peak) * 100 : 0; });
  const worst = Math.min(...dd, 0);
  const W = 600, H = 120, padT = 10, padB = 16;
  const lo = Math.min(worst * 1.15, -0.05);
  const x = (i: number) => (i / (dd.length - 1)) * W;
  const y = (v: number) => padT + (v / lo) * (H - padT - padB);
  const line = dd.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <div className="chartbox">
      <div className="chart-head"><span className="chart-title">{title}</span>
        <span className="chart-sub">worst {worst.toFixed(2)}%</span></div>
      <div className="chart-area">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 120, display: "block" }}>
          <defs><linearGradient id="ddfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(255,77,77,0.04)" /><stop offset="100%" stopColor="rgba(255,77,77,0.28)" /></linearGradient></defs>
          <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="var(--border-soft)" strokeWidth="1" vectorEffect="non-scaling-stroke" opacity="0.6" />
          <polygon points={`0,${y(0)} ${line} ${W},${y(0)}`} fill="url(#ddfill)" />
          <polyline points={line} fill="none" stroke="var(--loss)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        </svg>
        <span className="ylabel" style={{ top: "8%" }}>0%</span>
        <span className="ylabel" style={{ top: "82%" }}>{lo.toFixed(1)}%</span>
      </div>
    </div>
  );
}

/* Cost-to-break-even composition — exchange fee vs gas, spot vs perp. */
export function CostBars({ fees }: { fees: { breakeven_move_pct_incl_gas?: { spot: number; perp: number }; model?: { breakeven_move_pct?: { spot: number; perp: number } } } }) {
  const incl = fees?.breakeven_move_pct_incl_gas;
  const feeOnly = fees?.model?.breakeven_move_pct;
  if (!incl || !feeOnly) return <div className="chart-empty">no fee data yet</div>;
  const rows = ([["Spot", "spot"], ["Perp", "perp"]] as const).map(([label, k]) => ({
    label, total: incl[k], fee: feeOnly[k], gas: Math.max(0, incl[k] - feeOnly[k]),
  }));
  const max = Math.max(...rows.map((r) => r.total), 0.01);
  return (
    <div>
      <div className="bars">
        {rows.map((r) => (
          <div className="bar-row" key={r.label}>
            <span className="bar-label">{r.label}</span>
            <div className="bar-track" style={{ display: "flex" }}>
              <div className="bar costfee" style={{ width: `${(r.fee / max) * 100}%` }} title={`exchange fee ${r.fee}%`} />
              <div className="bar costgas" style={{ width: `${(r.gas / max) * 100}%` }} title={`gas ${r.gas.toFixed(2)}%`} />
            </div>
            <span className="bar-val">{r.total}%</span>
          </div>
        ))}
      </div>
      <div className="bookbar-key" style={{ marginTop: 8 }}>
        <span><i className="k costfee" /> exchange fee</span>
        <span><i className="k costgas" /> gas (fixed)</span>
      </div>
    </div>
  );
}

/* Per-strategy cumulative realized P/L — small multiples. */
export function StratMultiples({ series, labels }:
  { series: { t: number; by: Record<string, number> }[]; labels?: string[] }) {
  if (!series || series.length < 2) return <div className="chart-empty">accumulating per-strategy history…</div>;
  const keys = (labels && labels.length) ? labels
    : Array.from(new Set(series.flatMap((s) => Object.keys(s.by))));
  return (
    <div className="multiples">
      {keys.map((k) => {
        let last = 0;
        const arr = series.map((s) => { if (k in s.by) last = s.by[k]; return last; });
        const val = arr[arr.length - 1];
        return (
          <div key={k} className="mult">
            <div className="mult-head">
              <span className="mult-name">{k.replace(/_/g, " ")}</span>
              <span className={val >= 0 ? "mult-val pos" : "mult-val neg"}>{val >= 0 ? "+" : ""}{fmt(val)}</span>
            </div>
            <Sparkline data={arr} w={150} h={30} />
          </div>
        );
      })}
    </div>
  );
}
