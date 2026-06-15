"use client";

import { useEffect, useRef, useState } from "react";
import { useAgent, fmt } from "./useAgent";

type Risk = { risk_mode: string; max_positions: number };
type Status = {
  deposit_usd: number; realized_pnl_usd: number; unrealized_pnl_usd: number;
  equity_usd: number; open_positions: number; slots_used: number; slots_max: number;
  aggregate_drawdown_usd: number; kill_switch_fired: boolean; closed_trades: number;
  loop?: { markets?: number; risk_mode?: string; risk?: Risk; strategies?: string[];
    universe?: { markets?: number; candidates: number } };
};
type Pos = {
  symbol: string; tf: string; side?: string; market?: string; strategy?: string; level_kind?: string; state: string;
  avg_entry: number; notional_usd: number; gain_pct: number; peak_gain_pct: number;
  stop_pct: number | null; target_pct: number; averaging_done: number; leverage?: number;
};
type Trade = { symbol: string; tf: string; side?: string; market?: string; strategy?: string; pnl_usd: number; reason: string; closed: string | null };
type Trace = { symbol: string; tf: string; ts: string; strategy?: string; entered: boolean;
  gates: { step: string; passed: boolean; detail: string }[] };
type Strat = { active: string[]; open_positions_by_strategy: Record<string, number>;
  realized_pnl_by_strategy: Record<string, number> };
type Cfg = { perps_leverage?: number; perps_target_mult?: number; perp_data_source?: string;
  trade_mode?: string; allow_shorts?: boolean };

const SL: Record<string, string> = { reaction: "Reaction", momentum_breakout: "Breakout",
  mean_reversion: "Mean-Rev", trend_follow: "Trend", volatility_squeeze: "Squeeze",
  vwap_reversion: "VWAP", liquidity_sweep: "Sweep" };
const sLabel = (s?: string) => (s ? SL[s] ?? s.replace(/_/g, " ") : "—");
const Side = ({ s }: { s?: string }) => <span className={s === "short" ? "badge red" : "badge green"}>{(s ?? "long").toUpperCase()}</span>;
const Book = ({ m, lev }: { m?: string; lev?: number }) =>
  <span className={m === "perp" ? "badge gold" : "badge gray"}>
    {(m ?? "spot").toUpperCase()}{m === "perp" && lev && lev > 1 ? ` ${fmt(lev)}×` : ""}</span>;

// price formatter: more decimals for sub-dollar tokens, fewer for large prices
const px = (n: number) => {
  if (n == null) return "—";
  const d = n >= 100 ? 2 : n >= 1 ? 4 : n >= 0.01 ? 5 : 8;
  return n.toLocaleString("en-US", { maximumFractionDigits: d });
};
const pct = (n: number) => `${n >= 0 ? "+" : ""}${fmt(n)}%`;

function Spark({ data, up }: { data: number[]; up: boolean }) {
  if (!data || data.length < 2) return <div style={{ height: 54 }} />;
  const w = 280, h = 54; const min = Math.min(...data), max = Math.max(...data); const rng = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - 3 - ((v - min) / rng) * (h - 6)}`).join(" ");
  const col = up ? "var(--profit)" : "var(--loss)";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 54 }} preserveAspectRatio="none">
      <defs><linearGradient id="hsp" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={up ? "rgba(24,200,120,0.3)" : "rgba(255,77,77,0.28)"} />
        <stop offset="100%" stopColor="rgba(0,0,0,0)" /></linearGradient></defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill="url(#hsp)" />
      <polyline points={pts} fill="none" stroke={col} strokeWidth={1.75} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function Page() {
  const [status, live] = useAgent<Status | null>("/status", null);
  const [positions] = useAgent<Pos[]>("/positions", []);
  const [trades] = useAgent<Trade[]>("/trades", []);
  const [traces] = useAgent<Trace[]>("/traces?limit=40", []);
  const [strat] = useAgent<Strat | null>("/strategies", null);
  const [cfg] = useAgent<Cfg | null>("/config", null, 8000);

  const eqRef = useRef<number[]>([]);
  const [eq, setEq] = useState<number[]>([]);
  useEffect(() => {
    const e = status?.equity_usd;
    if (e == null) return;
    const a = eqRef.current;
    if (a.length === 0 || a[a.length - 1] !== e) {
      a.push(e); if (a.length > 90) a.shift(); setEq([...a]);
    }
  }, [status?.equity_usd]);

  const realized = status?.realized_pnl_usd ?? 0;
  const unreal = status?.unrealized_pnl_usd ?? 0;
  const pnl = realized + unreal;
  const wins = trades.filter((t) => t.pnl_usd > 0).length;
  const winRate = trades.length ? (wins / trades.length) * 100 : 0;
  const exposure = positions.reduce((a, p) => a + p.notional_usd, 0);
  const markets = status?.loop?.markets ?? status?.loop?.universe?.candidates ?? "—";
  const mode = status?.loop?.risk_mode ?? "—";
  const slotsMax = status?.slots_max ?? status?.loop?.risk?.max_positions ?? 5;
  const activeStrats = status?.loop?.strategies ?? strat?.active ?? [];

  return (
    <>
      <main className="main">
        {/* Hero band */}
        <div className="hero">
          <div className="hero-left">
            <div className="eyebrow">Command Center</div>
            <div className="hero-eq">${fmt(status?.equity_usd ?? 0)}</div>
            <div className="hero-sub">
              <span className={pnl >= 0 ? "pos" : "neg"}>{pnl >= 0 ? "▲ +" : "▼ "}{fmt(pnl)} USD</span>
              <span className="muted"> total P/L · realized {realized >= 0 ? "+" : ""}{fmt(realized)} · unrealized {unreal >= 0 ? "+" : ""}{fmt(unreal)}</span>
            </div>
            <div className="hero-tags">
              <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE · PAPER" : "OFFLINE"}</span>
              <span className={status?.kill_switch_fired ? "pill dead" : "pill"}><span className="dot" />
                {status?.kill_switch_fired ? "Kill Switch Fired" : live ? "Agents Running" : "Connecting…"}</span>
              <span className="badge gold" style={{ textTransform: "capitalize" }}>{mode} mode</span>
              <span className="badge cyan">{markets} markets</span>
              <span className="badge gold">{activeStrats.length} strategies</span>
              <span className="badge green">SPOT + PERPS{cfg?.perps_leverage ? ` · ${fmt(cfg.perps_leverage)}×` : ""}</span>
            </div>
          </div>
          <div className="hero-right">
            <div className="eyebrow" style={{ marginBottom: 6 }}>Equity · live</div>
            <Spark data={eq} up={pnl >= 0} />
          </div>
        </div>

        {/* KPI row */}
        <div className="cards" style={{ marginTop: 16 }}>
          <div className="card"><div className="lbl">Markets</div><div className="val cyan">{markets}</div></div>
          <div className="card"><div className="lbl">Win Rate</div><div className="val pos">{fmt(winRate)}%</div></div>
          <div className="card"><div className="lbl">Open Positions</div><div className="val">{status?.slots_used ?? 0}/{slotsMax}</div></div>
          <div className="card"><div className="lbl">Risk Exposure</div><div className="val">${fmt(exposure)}</div></div>
          <div className="card"><div className="lbl">Realized P/L</div><div className={realized >= 0 ? "val pos" : "val neg"}>{realized >= 0 ? "+" : ""}{fmt(realized)}</div></div>
          <div className="card"><div className="lbl">Closed Trades</div><div className="val">{status?.closed_trades ?? 0}</div></div>
        </div>

        {/* Strategy performance strip */}
        <h2 className="section">Strategy Performance</h2>
        <div className="strip">
          {(strat?.active ?? activeStrats).map((s) => {
            const open = strat?.open_positions_by_strategy?.[s] ?? 0;
            const sp = strat?.realized_pnl_by_strategy?.[s] ?? 0;
            return (
              <div key={s} className="strip-card">
                <div className="strip-name">{sLabel(s)}</div>
                <div className="strip-row"><span className="badge green">{open} open</span>
                  <span className={sp >= 0 ? "strip-pnl pos" : "strip-pnl neg"}>{sp >= 0 ? "+" : ""}{fmt(sp)}</span></div>
              </div>
            );
          })}
          {(strat?.active ?? activeStrats).length === 0 && <div className="strip-card"><div className="strip-name">Loading…</div></div>}
        </div>

        <h2 className="section">Open Positions</h2>
        <div className="tbl-wrap">
          <table>
            <thead><tr>
              <th>Market</th><th>Side</th><th>Book</th><th>Strategy</th><th>TF</th><th>State</th>
              <th className="num">Entry</th><th className="num">Size</th><th className="num">Gain</th>
              <th className="num">Peak</th><th className="num">Stop</th><th className="num">Target</th><th className="num">Adds</th>
            </tr></thead>
            <tbody>
              {positions.length === 0 && <tr><td colSpan={13} className="empty">No open positions — agents watching, waiting for gate confirmation.</td></tr>}
              {positions.map((p, i) => (
                <tr key={i}>
                  <td className="mkt">{p.symbol}<span className="quote">/USDT</span></td>
                  <td><Side s={p.side} /></td>
                  <td><Book m={p.market} lev={p.leverage} /></td>
                  <td><span className="badge cyan">{sLabel(p.strategy)}</span></td>
                  <td className="num dim">{p.tf}</td>
                  <td><span className={p.state === "sl_in_profit" ? "badge green" : "badge gold"}>{p.state === "sl_in_profit" ? "LOCKED" : "ACTIVE"}</span></td>
                  <td className="num">{px(p.avg_entry)}</td>
                  <td className="num">${fmt(p.notional_usd)}</td>
                  <td className={p.gain_pct >= 0 ? "num pos" : "num neg"}>{pct(p.gain_pct)}</td>
                  <td className="num dim">{pct(p.peak_gain_pct)}</td>
                  <td className="num dim">{p.stop_pct != null ? pct(p.stop_pct) : "—"}</td>
                  <td className="num dim">{fmt(p.target_pct)}%</td>
                  <td className="num dim">{p.averaging_done}/2</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="section">Recent Decisions</h2>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th className="num">Time</th><th>Market</th><th>Strategy</th><th>TF</th><th>Gate Audit</th><th>Result</th></tr></thead>
            <tbody>
              {traces.length === 0 && <tr><td colSpan={6} className="empty">No evaluations yet — markets warming up.</td></tr>}
              {[...traces].reverse().slice(0, 14).map((t, i) => (
                <tr key={i}>
                  <td className="num dim">{new Date(t.ts).toLocaleTimeString()}</td>
                  <td className="mkt">{t.symbol}</td>
                  <td><span className="badge cyan">{sLabel(t.strategy)}</span></td>
                  <td className="num dim">{t.tf}</td>
                  <td className="gates-cell">{t.gates.map((g, j) => (<span key={j} className={g.passed ? "gate ok" : "gate no"} title={g.detail}>{g.step.replace(/_/g, " ")}</span>))}</td>
                  <td>{t.entered ? <span className="badge green">ENTERED</span> : <span className="badge gray">SKIPPED</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="section">Closed Trades</h2>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Market</th><th>Side</th><th>Book</th><th>Strategy</th><th>TF</th><th>Exit</th><th className="num">P/L</th><th className="num">Closed</th></tr></thead>
            <tbody>
              {trades.length === 0 && <tr><td colSpan={8} className="empty">No closed trades yet.</td></tr>}
              {[...trades].reverse().slice(0, 20).map((t, i) => (
                <tr key={i}>
                  <td className="mkt">{t.symbol}<span className="quote">/USDT</span></td>
                  <td><Side s={t.side} /></td>
                  <td><Book m={t.market} /></td>
                  <td><span className="badge cyan">{sLabel(t.strategy)}</span></td>
                  <td className="num dim">{t.tf}</td>
                  <td><span className={t.reason === "take_profit" ? "badge green" : t.reason === "kill_switch" || t.reason === "hard_stop" ? "badge red" : "badge gold"}>{t.reason.replace(/_/g, " ").toUpperCase()}</span></td>
                  <td className={t.pnl_usd >= 0 ? "num pos" : "num neg"}>{t.pnl_usd >= 0 ? "+" : ""}{fmt(t.pnl_usd)}</td>
                  <td className="num dim">{t.closed ? new Date(t.closed).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>

      <aside className="rail">
        <div>
          <h2 className="section">Agent Activity Feed</h2>
          <div className="feed">
            {[...traces].reverse().slice(0, 9).map((t, i) => {
              const lg = t.gates[t.gates.length - 1];
              return (
                <div key={i} className={t.entered ? "feed-item entered" : "feed-item blocked"}>
                  <div className="when">{new Date(t.ts).toLocaleTimeString()} — {t.symbol} {t.tf} · {sLabel(t.strategy)}</div>
                  <div className="what">{t.entered ? <><b>Entered</b> — all gates confirmed, limit filled.</> : <><b>Skipped</b> — {lg ? (lg.detail || lg.step.replace(/_/g, " ") + " not confirmed") : "awaiting confirmation"}.</>}</div>
                </div>
              );
            })}
            {traces.length === 0 && <div className="feed-item"><div className="what">Watching markets…</div></div>}
          </div>
        </div>
        <div className="vault">
          <div className="title">🜲 Risk Vault</div>
          <div className="row"><span>Risk Mode</span><span className="v" style={{ textTransform: "capitalize" }}>{mode}</span></div>
          <div className="row"><span>Perps Leverage</span><span className="v">{cfg?.perps_leverage ? `${fmt(cfg.perps_leverage)}×` : "—"}</span></div>
          <div className="row"><span>Position Slots</span><span className="v">{status?.slots_used ?? 0} / {slotsMax}</span></div>
          <div className="row"><span>Open Exposure</span><span className="v">${fmt(exposure)}</span></div>
          <div className="row"><span>Aggregate Drawdown</span><span className="v">${fmt(status?.aggregate_drawdown_usd ?? 0)}</span></div>
          <div className="row"><span>Kill Switch</span><span className={status?.kill_switch_fired ? "v danger" : "v"}>{status?.kill_switch_fired ? "FIRED" : "Armed"}</span></div>
        </div>
      </aside>
    </>
  );
}
