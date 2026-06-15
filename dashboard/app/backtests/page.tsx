"use client";

import { useEffect, useState } from "react";
import { fmt } from "../useAgent";

type BT = {
  symbol: string; timeframe: string; strategy: string; bars: number; trades: number;
  win_rate_pct: number; total_pnl_usd: number; return_pct: number; max_drawdown_pct: number;
  profit_factor: number; sharpe: number; kill_switch_fired: boolean; source?: string;
  close_reasons: Record<string, number>; equity_curve: number[]; error?: string;
};
type Uni = {
  timeframe: string; markets_tested: number; markets_skipped: string[];
  trades: number; win_rate_pct: number; total_pnl_usd: number;
  avg_return_pct_per_market: number; worst_drawdown_pct: number;
  winners: number; losers: number; universe_size: number; source: string; cached: boolean;
  per_symbol: { symbol: string; trades: number; win_rate_pct: number; total_pnl_usd: number;
    return_pct: number; max_drawdown_pct: number; profit_factor: number }[];
};

const SYMBOLS = ["BNB", "CAKE", "ETH", "XVS", "FLOKI", "TWT", "DOGE", "PEPE", "INJ", "NEAR"];
const TFS = ["3m", "10m", "15m", "30m", "4h"];
const STRATS = ["portfolio", "reaction", "momentum_breakout", "mean_reversion", "trend_follow", "volatility_squeeze"];
const SOURCES = ["synthetic", "cmc", "checkpoint"];

function Equity({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null;
  const w = 760, h = 150, pad = 4;
  const min = Math.min(...data), max = Math.max(...data); const rng = max - min || 1;
  const x = (i: number) => (i / (data.length - 1)) * w;
  const y = (v: number) => pad + (1 - (v - min) / rng) * (h - pad * 2);
  const line = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const up = data[data.length - 1] >= data[0]; const col = up ? "var(--profit)" : "var(--loss)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 150, display: "block" }} preserveAspectRatio="none">
      <defs><linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={up ? "rgba(24,200,120,0.28)" : "rgba(255,77,77,0.26)"} />
        <stop offset="100%" stopColor="rgba(0,0,0,0)" /></linearGradient></defs>
      <polygon points={`0,${h} ${line} ${w},${h}`} fill="url(#eq)" />
      <polyline points={line} fill="none" stroke={col} strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function Backtests() {
  const [mode, setMode] = useState<"single" | "all">("single");
  const [source, setSource] = useState("synthetic");
  const [symbol, setSymbol] = useState("BNB");
  const [tf, setTf] = useState("15m");
  const [strat, setStrat] = useState("portfolio");
  const [bars, setBars] = useState("800");
  const [limit, setLimit] = useState("12");
  const [res, setRes] = useState<BT | null>(null);
  const [uni, setUni] = useState<Uni | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const runSingle = async () => {
    setBusy(true); setErr("");
    try {
      const r = await fetch(`/agent/backtest?symbol=${symbol}&timeframe=${tf}&strategy=${strat}&bars=${bars}&source=${source}`);
      const j = await r.json();
      if (j.error) { setErr(j.error); setRes(null); } else setRes(j);
    } catch { setErr("agent offline"); }
    setBusy(false);
  };
  const runAll = async () => {
    setBusy(true); setErr("");
    try {
      const r = await fetch(`/agent/portfolio-backtest?timeframe=${tf}&bars=${Math.min(+bars, 800)}&limit=${limit}&source=${source}`);
      setUni(await r.json());
    } catch { setErr("agent offline"); }
    setBusy(false);
  };
  const run = () => (mode === "single" ? runSingle() : runAll());
  useEffect(() => { runSingle(); /* eslint-disable-next-line */ }, []);

  const field = (label: string, val: string, set: (v: string) => void, opts: string[]) => (
    <div className="sel-wrap"><span className="sel-lbl">{label}</span>
      <select className="sel" value={val} onChange={(e) => set(e.target.value)}>
        {opts.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
      </select></div>
  );

  return (
    <main className="main">
      <div className="toolbar">
        <span className="badge gold">VERIFICATION BACKTESTS</span>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          Same engine as the live agent — a spec's backtest is exactly what Binacci would have done.</span>
      </div>

      <div className="toolbar">
        <button className={mode === "single" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setMode("single")}>Single market</button>
        <button className={mode === "all" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setMode("all")}>All markets</button>
      </div>

      <div className="toolbar" style={{ alignItems: "flex-end" }}>
        {field("Source", source, setSource, SOURCES)}
        {mode === "single" && field("Market", symbol, setSymbol, SYMBOLS)}
        {field("Timeframe", tf, setTf, TFS)}
        {mode === "single" && field("Strategy", strat, setStrat, STRATS)}
        {mode === "single"
          ? field("Bars", bars, setBars, ["500", "800", "1200", "1500"])
          : field("Markets", limit, setLimit, ["8", "12", "20", "40", "58"])}
        <button className="btn btn-primary" onClick={run} disabled={busy} style={{ height: 36 }}>
          {busy ? "Running…" : mode === "single" ? "▶ Run Backtest" : "▶ Run Universe"}</button>
        {err && <span className="badge red">{err}</span>}
      </div>

      {source !== "synthetic" && (
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "-6px 0 14px" }}>
          {source} source needs the agent configured with a CMC key + OHLCV plan (or accumulated checkpoint data).
          Markets without enough data are skipped, not failed.
        </p>
      )}

      {mode === "single" && res && (
        <>
          <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
            <div className="card"><div className="lbl">Trades</div><div className="val">{res.trades}</div></div>
            <div className="card"><div className="lbl">Win Rate</div><div className="val pos">{fmt(res.win_rate_pct)}%</div></div>
            <div className="card"><div className="lbl">Return</div>
              <div className={res.return_pct >= 0 ? "val pos" : "val neg"}>{res.return_pct >= 0 ? "+" : ""}{fmt(res.return_pct)}%</div></div>
            <div className="card"><div className="lbl">Max Drawdown</div><div className="val">{fmt(res.max_drawdown_pct)}%</div></div>
            <div className="card"><div className="lbl">Profit Factor</div><div className="val cyan">{res.profit_factor > 99 ? "∞" : fmt(res.profit_factor)}</div></div>
            <div className="card"><div className="lbl">Sharpe</div><div className="val">{fmt(res.sharpe)}</div></div>
          </div>
          <h2 className="section">Equity Curve</h2>
          <div className="chart-box"><Equity data={res.equity_curve} /></div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 12 }}>
            {res.strategy === "portfolio" ? "Full portfolio" : res.strategy.replace(/_/g, " ")} · {res.symbol}/{res.timeframe} · {res.bars} bars · {res.source} data
          </p>
        </>
      )}

      {mode === "all" && uni && (
        <>
          <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
            <div className="card"><div className="lbl">Markets</div><div className="val cyan">{uni.markets_tested}</div></div>
            <div className="card"><div className="lbl">Winners</div><div className="val pos">{uni.winners}</div></div>
            <div className="card"><div className="lbl">Losers</div><div className="val neg">{uni.losers}</div></div>
            <div className="card"><div className="lbl">Win Rate</div><div className="val pos">{fmt(uni.win_rate_pct)}%</div></div>
            <div className="card"><div className="lbl">Total P/L</div>
              <div className={uni.total_pnl_usd >= 0 ? "val pos" : "val neg"}>{uni.total_pnl_usd >= 0 ? "+" : ""}${fmt(uni.total_pnl_usd)}</div></div>
            <div className="card"><div className="lbl">Avg Ret / Mkt</div>
              <div className={uni.avg_return_pct_per_market >= 0 ? "val pos" : "val neg"}>{uni.avg_return_pct_per_market >= 0 ? "+" : ""}{fmt(uni.avg_return_pct_per_market)}%</div></div>
          </div>

          <h2 className="section">Per-Market Results — {uni.markets_tested} of {uni.universe_size} markets · {uni.source} data{uni.cached ? " · cached" : ""}</h2>
          <div className="tbl-wrap tall">
            <table>
              <thead><tr><th>Market</th><th>Trades</th><th>Win %</th><th>P/L</th><th>Return</th><th>Max DD</th><th>PF</th></tr></thead>
              <tbody>
                {uni.per_symbol.map((p) => (
                  <tr key={p.symbol}>
                    <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{p.symbol}/USDT</td>
                    <td className="num">{p.trades}</td>
                    <td className="num">{fmt(p.win_rate_pct)}%</td>
                    <td className={p.total_pnl_usd >= 0 ? "num pos" : "num neg"}>{p.total_pnl_usd >= 0 ? "+" : ""}{fmt(p.total_pnl_usd)}</td>
                    <td className={p.return_pct >= 0 ? "num pos" : "num neg"}>{p.return_pct >= 0 ? "+" : ""}{fmt(p.return_pct)}%</td>
                    <td className="num">{fmt(p.max_drawdown_pct)}%</td>
                    <td className="num">{p.profit_factor > 99 ? "∞" : fmt(p.profit_factor)}</td>
                  </tr>
                ))}
                {uni.per_symbol.length === 0 && <tr><td colSpan={7}>no markets had enough data on this source</td></tr>}
              </tbody>
            </table>
          </div>
          {uni.markets_skipped.length > 0 && (
            <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 10 }}>
              Skipped (insufficient data): {uni.markets_skipped.join(", ")}</p>
          )}
        </>
      )}
    </main>
  );
}
