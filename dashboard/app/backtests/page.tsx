"use client";

import { useEffect, useState } from "react";
import { fmt } from "../useAgent";

type BT = {
  symbol: string; timeframe: string; strategy: string; bars: number; trades: number;
  win_rate_pct: number; total_pnl_usd: number; return_pct: number; max_drawdown_pct: number;
  profit_factor: number; sharpe: number; kill_switch_fired: boolean;
  close_reasons: Record<string, number>; equity_curve: number[];
};

const SYMBOLS = ["BNB", "CAKE", "ETH", "XVS", "FLOKI", "TWT", "DOGE", "PEPE", "INJ", "NEAR"];
const TFS = ["3m", "10m", "15m", "30m", "4h"];
const STRATS = ["portfolio", "reaction", "momentum_breakout", "mean_reversion", "trend_follow", "volatility_squeeze"];

function Equity({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null;
  const w = 760, h = 150, pad = 4;
  const min = Math.min(...data), max = Math.max(...data);
  const rng = max - min || 1;
  const x = (i: number) => (i / (data.length - 1)) * w;
  const y = (v: number) => pad + (1 - (v - min) / rng) * (h - pad * 2);
  const line = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const area = `0,${h} ${line} ${w},${h}`;
  const up = data[data.length - 1] >= data[0];
  const col = up ? "var(--profit)" : "var(--loss)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 150, display: "block" }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={up ? "rgba(24,200,120,0.28)" : "rgba(255,77,77,0.26)"} />
          <stop offset="100%" stopColor="rgba(0,0,0,0)" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#eq)" />
      <polyline points={line} fill="none" stroke={col} strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function Backtests() {
  const [symbol, setSymbol] = useState("BNB");
  const [tf, setTf] = useState("15m");
  const [strat, setStrat] = useState("portfolio");
  const [bars, setBars] = useState("800");
  const [res, setRes] = useState<BT | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    setBusy(true); setErr("");
    try {
      const r = await fetch(`/agent/backtest?symbol=${symbol}&timeframe=${tf}&strategy=${strat}&bars=${bars}`);
      if (!r.ok) throw new Error(String(r.status));
      setRes(await r.json());
    } catch { setErr("agent offline or backtest failed"); }
    setBusy(false);
  };
  useEffect(() => { run(); /* eslint-disable-next-line */ }, []);

  const field = (label: string, val: string, set: (v: string) => void, opts: string[]) => (
    <div className="sel-wrap">
      <span className="sel-lbl">{label}</span>
      <select className="sel" value={val} onChange={(e) => set(e.target.value)}>
        {opts.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
      </select>
    </div>
  );

  return (
    <main className="main">
      <div className="toolbar">
        <span className="badge gold">VERIFICATION BACKTESTS</span>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          Same engine as the live agent — a spec's backtest is exactly what Binacci would have done.</span>
      </div>

      <div className="toolbar" style={{ alignItems: "flex-end" }}>
        {field("Market", symbol, setSymbol, SYMBOLS)}
        {field("Timeframe", tf, setTf, TFS)}
        {field("Strategy", strat, setStrat, STRATS)}
        {field("Bars", bars, setBars, ["500", "800", "1200", "1500"])}
        <button className="btn btn-primary" onClick={run} disabled={busy} style={{ height: 36 }}>
          {busy ? "Running…" : "▶ Run Backtest"}</button>
        {err && <span className="badge red">{err}</span>}
      </div>

      {res && (
        <>
          <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
            <div className="card"><div className="lbl">Trades</div><div className="val">{res.trades}</div></div>
            <div className="card"><div className="lbl">Win Rate</div><div className="val pos">{fmt(res.win_rate_pct)}%</div></div>
            <div className="card"><div className="lbl">Return</div>
              <div className={res.return_pct >= 0 ? "val pos" : "val neg"}>{res.return_pct >= 0 ? "+" : ""}{fmt(res.return_pct)}%</div></div>
            <div className="card"><div className="lbl">Max Drawdown</div><div className="val">{fmt(res.max_drawdown_pct)}%</div></div>
            <div className="card"><div className="lbl">Profit Factor</div>
              <div className="val cyan">{res.profit_factor > 99 ? "∞" : fmt(res.profit_factor)}</div></div>
            <div className="card"><div className="lbl">Sharpe</div><div className="val">{fmt(res.sharpe)}</div></div>
          </div>

          <h2 className="section">Equity Curve</h2>
          <div className="chart-box"><Equity data={res.equity_curve} /></div>

          <h2 className="section">Exit Reasons</h2>
          <div className="vault" style={{ maxWidth: 520 }}>
            {Object.entries(res.close_reasons || {}).map(([k, v]) => (
              <div key={k} className="row"><span style={{ textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</span><span className="v">{v}</span></div>
            ))}
            {Object.keys(res.close_reasons || {}).length === 0 && <div className="row"><span>No closed trades in window</span></div>}
            <div className="row"><span>Kill switch</span>
              <span className={res.kill_switch_fired ? "v danger" : "v"}>{res.kill_switch_fired ? "FIRED" : "Never tripped"}</span></div>
          </div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 12 }}>
            {res.strategy === "portfolio" ? "Full strategy portfolio" : res.strategy.replace(/_/g, " ")} · {res.symbol}/{res.timeframe} · {res.bars} bars · synthetic OHLCV
          </p>
        </>
      )}
    </main>
  );
}
