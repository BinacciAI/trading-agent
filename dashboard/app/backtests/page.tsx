"use client";

import { useEffect, useRef, useState } from "react";
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
type TBRow = { timeframe: string; minutes_per_bar: number; bars: number; total_days: number; span: string };
type Grp = { trades: number; win_rate_pct: number; total_pnl_usd: number; avg_pnl_usd?: number };
type FullBT = {
  config: { risk_mode: string; perps_leverage: number; perps_target_mult: number;
    bars_per_run: number; deposit_usd_per_run: number; markets_in_universe: number;
    timeframes: string[]; perp_strategies: string[] };
  portfolio: { runs_attempted: number; runs_completed: number; runs_skipped: number;
    trades: number; win_rate_pct: number; total_pnl_usd: number; avg_return_pct_per_run: number;
    worst_drawdown_pct: number; winning_runs: number; losing_runs: number };
  by_timeframe: Record<string, { markets_tested: number; trades: number; win_rate_pct: number;
    total_pnl_usd: number; timebasis: TBRow }>;
  by_strategy: Record<string, Grp>;
  by_market: Record<string, Grp>;
  time_basis: TBRow[];
  top_markets: { symbol: string; trades: number; win_rate_pct: number; total_pnl_usd: number }[];
  source: string; cached: boolean;
};

const SYMBOLS = ["BNB", "CAKE", "ETH", "XVS", "FLOKI", "TWT", "DOGE", "PEPE", "INJ", "NEAR"];
const TFS = ["3m", "10m", "15m", "30m", "45m", "89m", "4h", "1d"];
const STRATS = ["portfolio", "reaction", "momentum_breakout", "mean_reversion", "trend_follow",
  "volatility_squeeze", "vwap_reversion", "liquidity_sweep"];
const SOURCES = ["synthetic", "cmc", "checkpoint"];
const TF_PRESETS = ["3m,15m,4h", "15m,4h,1d", "3m,15m,45m,4h,1d", "15m,1d"];
const MKT_LIMITS = ["20", "40", "80", "146"];
const RISK_MODES = ["balanced", "conservative", "aggressive"];

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

function TimeBasisChart({ rows, bars }: { rows: TBRow[]; bars: number }) {
  if (!rows || rows.length === 0) return null;
  const sorted = [...rows].sort((a, b) => a.minutes_per_bar - b.minutes_per_bar);
  // log scale so 3.1 days and 4.1 years both read on one chart
  const L = (d: number) => Math.log10(Math.max(d, 0.01) + 1);
  const maxL = Math.max(...sorted.map((r) => L(r.total_days))) || 1;
  const rowH = 30, gap = 8, labelW = 56, spanW = 92;
  const h = sorted.length * (rowH + gap);
  return (
    <div className="chart-box" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 10 }}>
        What <b style={{ color: "var(--brand-gold)" }}>{bars.toLocaleString()}</b> candles span in real time, per timeframe
      </div>
      <svg viewBox={`0 0 760 ${h}`} style={{ width: "100%", height: h, display: "block" }} preserveAspectRatio="none">
        {sorted.map((r, i) => {
          const y = i * (rowH + gap);
          const barW = (760 - labelW - spanW - 8) * (L(r.total_days) / maxL);
          return (
            <g key={r.timeframe}>
              <text x={0} y={y + rowH / 2 + 4} fill="var(--text-primary)" fontSize={13} fontWeight={600}>{r.timeframe}</text>
              <rect x={labelW} y={y + 4} width={Math.max(barW, 2)} height={rowH - 8} rx={3}
                fill="var(--brand-gold)" opacity={0.85} />
              <text x={labelW + Math.max(barW, 2) + 8} y={y + rowH / 2 + 4} fill="var(--text-secondary)" fontSize={12}>
                {r.span}
              </text>
            </g>
          );
        })}
      </svg>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
        Bar length is log-scaled (a day and a year fit one axis). Exact: bars × minutes/bar.
      </div>
    </div>
  );
}

export default function Backtests() {
  const [mode, setMode] = useState<"single" | "all" | "full">("single");
  const [source, setSource] = useState("synthetic");
  const [symbol, setSymbol] = useState("BNB");
  const [tf, setTf] = useState("15m");
  const [strat, setStrat] = useState("portfolio");
  const [bars, setBars] = useState("800");
  const [limit, setLimit] = useState("12");
  const [tfPreset, setTfPreset] = useState("15m,4h,1d");
  const [mlimit, setMlimit] = useState("40");
  const [riskMode, setRiskMode] = useState("balanced");
  const [res, setRes] = useState<BT | null>(null);
  const [uni, setUni] = useState<Uni | null>(null);
  const [full, setFull] = useState<FullBT | null>(null);
  const [tb, setTb] = useState<TBRow[]>([]);
  const [prog, setProg] = useState<{ done: number; total: number; elapsed: number } | null>(null);
  const pollId = useRef(0);
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
  const runFull = async () => {
    const myId = ++pollId.current;       // cancels any in-flight poll
    setBusy(true); setErr(""); setFull(null); setProg({ done: 0, total: 0, elapsed: 0 });
    const url = `/agent/full-backtest?timeframes=${tfPreset}&bars=${bars}`
      + `&limit=${mlimit === "146" ? 0 : mlimit}&source=${source}&risk_mode=${riskMode}`;
    const MAX_POLLS = 600;               // ~20 min ceiling at 2s
    for (let i = 0; i < MAX_POLLS; i++) {
      if (pollId.current !== myId) return;   // a newer run superseded this one
      let j: FullBT & { status?: string; progress?: number; total?: number; elapsed_s?: number; error?: string };
      try {
        const r = await fetch(url);
        j = await r.json();
      } catch { setErr("agent offline"); setBusy(false); setProg(null); return; }
      if (j.status === "running") {
        setProg({ done: j.progress ?? 0, total: j.total ?? 0, elapsed: j.elapsed_s ?? 0 });
        await new Promise((res) => setTimeout(res, 2000));
        continue;
      }
      if (j.status === "error") { setErr(j.error || "backtest failed"); setBusy(false); setProg(null); return; }
      // done (status "done", or a legacy direct result with a config)
      if (j.config) { setFull(j); if (j.time_basis) setTb(j.time_basis); }
      else setErr("unexpected response");
      setBusy(false); setProg(null);
      return;
    }
    setErr("timed out — try fewer markets or a higher eval cadence"); setBusy(false); setProg(null);
  };
  const loadTimebasis = async () => {
    try {
      const r = await fetch(`/agent/timebasis?bars=${bars}&timeframes=${tfPreset}`);
      const j = await r.json();
      if (j?.rows) setTb(j.rows);
    } catch { /* leave previous */ }
  };
  const run = () => (mode === "single" ? runSingle() : mode === "all" ? runAll() : runFull());
  useEffect(() => { runSingle(); /* eslint-disable-next-line */ }, []);
  useEffect(() => { if (mode === "full") loadTimebasis(); /* eslint-disable-next-line */ }, [mode, bars, tfPreset]);

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
        <button className={mode === "full" ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setMode("full")}>Full universe + time basis</button>
      </div>

      <div className="toolbar" style={{ alignItems: "flex-end" }}>
        {field("Source", source, setSource, SOURCES)}
        {mode === "single" && field("Market", symbol, setSymbol, SYMBOLS)}
        {mode !== "full" && field("Timeframe", tf, setTf, TFS)}
        {mode === "single" && field("Strategy", strat, setStrat, STRATS)}
        {mode === "full" && field("Timeframes", tfPreset, setTfPreset, TF_PRESETS)}
        {mode === "full" && field("Risk mode", riskMode, setRiskMode, RISK_MODES)}
        {mode === "single" && field("Bars", bars, setBars, ["500", "800", "1200", "1500"])}
        {mode === "all" && field("Markets", limit, setLimit, ["8", "12", "20", "40", "58"])}
        {mode === "full" && field("Bars", bars, setBars, ["500", "800", "1200", "1500"])}
        {mode === "full" && field("Markets", mlimit, setMlimit, MKT_LIMITS)}
        <button className="btn btn-primary" onClick={run} disabled={busy} style={{ height: 36 }}>
          {busy ? "Running…" : mode === "single" ? "▶ Run Backtest" : mode === "all" ? "▶ Run Universe" : "▶ Run Full Universe"}</button>
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
      {mode === "full" && (
        <>
          <h2 className="section">Time Basis — What a Candle Count Means in Real Time</h2>
          <TimeBasisChart rows={tb} bars={parseInt(bars, 10) || 1500} />

          {prog && (
            <div className="chart-box" style={{ padding: "14px 16px", marginTop: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>
                <span>Running backtest across the universe…{prog.total ? ` ${prog.done}/${prog.total} runs` : ""}</span>
                <span className="dim">{prog.elapsed ? `${fmt(prog.elapsed)}s` : ""}</span>
              </div>
              <div style={{ height: 8, background: "var(--bg-card)", borderRadius: 4, overflow: "hidden", border: "1px solid var(--border-soft)" }}>
                <div style={{ width: `${prog.total ? Math.min((prog.done / prog.total) * 100, 100) : 6}%`, height: "100%", background: "var(--brand-gold)", transition: "width .4s" }} />
              </div>
              <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
                Runs in the background — you can leave this open. All 146 markets across several timeframes is heavy
                (minutes); results are cached for 15 min once complete.
              </p>
            </div>
          )}

          {full && full.config && (
            <>
              <div className="toolbar" style={{ marginTop: 16 }}>
                <span className="badge gold">{full.config.markets_in_universe} MARKETS</span>
                <span className="badge cyan">{full.config.timeframes.join(" · ")}</span>
                <span className="badge gold" style={{ textTransform: "capitalize" }}>{full.config.risk_mode} · {fmt(full.config.perps_leverage)}× perps</span>
                <span className="badge gray">TP ×{fmt(full.config.perps_target_mult)}</span>
                <span className="badge gray">{full.source} data{full.cached ? " · cached" : ""}</span>
              </div>

              <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
                <div className="card"><div className="lbl">Runs</div><div className="val cyan">{full.portfolio.runs_completed}/{full.portfolio.runs_attempted}</div></div>
                <div className="card"><div className="lbl">Trades</div><div className="val">{full.portfolio.trades}</div></div>
                <div className="card"><div className="lbl">Win Rate</div><div className="val pos">{fmt(full.portfolio.win_rate_pct)}%</div></div>
                <div className="card"><div className="lbl">Total P/L</div>
                  <div className={full.portfolio.total_pnl_usd >= 0 ? "val pos" : "val neg"}>{full.portfolio.total_pnl_usd >= 0 ? "+" : ""}${fmt(full.portfolio.total_pnl_usd)}</div></div>
                <div className="card"><div className="lbl">Avg Ret / Run</div>
                  <div className={full.portfolio.avg_return_pct_per_run >= 0 ? "val pos" : "val neg"}>{full.portfolio.avg_return_pct_per_run >= 0 ? "+" : ""}{fmt(full.portfolio.avg_return_pct_per_run)}%</div></div>
                <div className="card"><div className="lbl">Worst Drawdown</div><div className="val neg">{fmt(full.portfolio.worst_drawdown_pct)}%</div></div>
              </div>

              <h2 className="section">By Book — Spot vs Perps</h2>
              <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                {Object.entries(full.by_market).map(([k, v]) => (
                  <div key={k} className="card">
                    <div className="lbl" style={{ textTransform: "uppercase" }}>{k} book</div>
                    <div className={v.total_pnl_usd >= 0 ? "val pos" : "val neg"}>{v.total_pnl_usd >= 0 ? "+" : ""}${fmt(v.total_pnl_usd)}</div>
                    <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>{v.trades} trades · {fmt(v.win_rate_pct)}% win</p>
                  </div>
                ))}
              </div>

              <h2 className="section">By Strategy</h2>
              <div className="tbl-wrap">
                <table>
                  <thead><tr><th>Strategy</th><th>Trades</th><th>Win %</th><th>Total P/L</th><th>Avg P/L</th></tr></thead>
                  <tbody>
                    {Object.entries(full.by_strategy).map(([k, v]) => (
                      <tr key={k}>
                        <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{k.replace(/_/g, " ")}{full.config.perp_strategies.includes(k) ? <span className="badge gold" style={{ marginLeft: 8 }}>PERP</span> : ""}</td>
                        <td className="num">{v.trades}</td>
                        <td className="num">{fmt(v.win_rate_pct)}%</td>
                        <td className={v.total_pnl_usd >= 0 ? "num pos" : "num neg"}>{v.total_pnl_usd >= 0 ? "+" : ""}{fmt(v.total_pnl_usd)}</td>
                        <td className={(v.avg_pnl_usd ?? 0) >= 0 ? "num pos" : "num neg"}>{(v.avg_pnl_usd ?? 0) >= 0 ? "+" : ""}{fmt(v.avg_pnl_usd ?? 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h2 className="section">By Timeframe — with Time Basis</h2>
              <div className="tbl-wrap">
                <table>
                  <thead><tr><th>TF</th><th>Span ({full.config.bars_per_run} bars)</th><th>Markets</th><th>Trades</th><th>Win %</th><th>Total P/L</th></tr></thead>
                  <tbody>
                    {Object.entries(full.by_timeframe).map(([k, v]) => (
                      <tr key={k}>
                        <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{k}</td>
                        <td className="dim">{v.timebasis?.span ?? "—"}</td>
                        <td className="num">{v.markets_tested}</td>
                        <td className="num">{v.trades}</td>
                        <td className="num">{fmt(v.win_rate_pct)}%</td>
                        <td className={v.total_pnl_usd >= 0 ? "num pos" : "num neg"}>{v.total_pnl_usd >= 0 ? "+" : ""}{fmt(v.total_pnl_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {full.top_markets?.length > 0 && (
                <>
                  <h2 className="section">Top Markets</h2>
                  <div className="tbl-wrap">
                    <table>
                      <thead><tr><th>Market</th><th>Trades</th><th>Win %</th><th>Total P/L</th></tr></thead>
                      <tbody>
                        {full.top_markets.slice(0, 12).map((m) => (
                          <tr key={m.symbol}>
                            <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{m.symbol}/USDT</td>
                            <td className="num">{m.trades}</td>
                            <td className="num">{fmt(m.win_rate_pct)}%</td>
                            <td className={m.total_pnl_usd >= 0 ? "num pos" : "num neg"}>{m.total_pnl_usd >= 0 ? "+" : ""}{fmt(m.total_pnl_usd)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </>
          )}
          {!full && (
            <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 12 }}>
              The full run backtests every market across the chosen timeframes and breaks results down by
              strategy and by book. Heavy — it is cached for 15 minutes after the first run.
            </p>
          )}
        </>
      )}
    </main>
  );
}
