"use client";

import { fmt } from "./useAgent";

/* Equity area chart — non-zero baseline (variation is the signal), gradient
   fill, crisp HTML y-labels overlaid so text never distorts. */
export function EquityArea({ data, title, sub }: { data: number[]; title: string; sub?: string }) {
  if (!data || data.length < 2) {
    return (
      <div className="chartbox">
        <div className="chart-head"><span className="chart-title">{title}</span></div>
        <div className="chart-empty">accumulating equity history…</div>
      </div>
    );
  }
  const W = 600, H = 150, pad = 6;
  const min = Math.min(...data), max = Math.max(...data), rng = max - min || 1;
  const x = (i: number) => (i / (data.length - 1)) * W;
  const y = (v: number) => H - pad - ((v - min) / rng) * (H - 2 * pad);
  const line = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  const col = up ? "var(--profit)" : "var(--loss)";
  return (
    <div className="chartbox">
      <div className="chart-head">
        <span className="chart-title">{title}</span>
        {sub && <span className="chart-sub">{sub}</span>}
      </div>
      <div className="chart-area">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: "100%", height: 150, display: "block" }}>
          <defs>
            <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={up ? "rgba(24,200,120,0.26)" : "rgba(255,77,77,0.24)"} />
              <stop offset="100%" stopColor="rgba(0,0,0,0)" />
            </linearGradient>
          </defs>
          <polygon points={`0,${H} ${line} ${W},${H}`} fill="url(#eqfill)" />
          <polyline points={line} fill="none" stroke={col} strokeWidth={2} vectorEffect="non-scaling-stroke" />
        </svg>
        <span className="ylabel ymax">${fmt(max)}</span>
        <span className="ylabel ymin">${fmt(min)}</span>
      </div>
    </div>
  );
}

/* Ranked horizontal bars from zero — for P/L attribution. Sorted by value,
   colored by sign, value labelled. */
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
