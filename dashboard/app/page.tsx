"use client";

import { useAgent, fmt } from "./useAgent";

type Risk = { risk_mode: string; max_positions: number; max_deployed_pct_of_deposit: number };
type Status = {
  deposit_usd: number; realized_pnl_usd: number; unrealized_pnl_usd: number;
  equity_usd: number; open_positions: number; slots_used: number; slots_max: number;
  aggregate_drawdown_usd: number; kill_switch_fired: boolean; closed_trades: number;
  loop?: {
    markets?: number; risk_mode?: string; risk?: Risk; strategies?: string[];
    universe?: { markets?: number; polled?: number; candidates: number; verified_count: number | null };
  };
};
type Pos = {
  symbol: string; tf: string; strategy?: string; level_kind?: string; state: string;
  avg_entry: number; notional_usd: number; gain_pct: number; peak_gain_pct: number;
  stop_pct: number | null; target_pct: number; averaging_done: number;
};
type Trade = { symbol: string; tf: string; strategy?: string; pnl_usd: number; reason: string; closed: string | null };
type Trace = {
  symbol: string; tf: string; ts: string; strategy?: string; entered: boolean;
  gates: { step: string; passed: boolean; detail: string }[];
};

const STRAT_LABEL: Record<string, string> = {
  reaction: "Reaction", momentum_breakout: "Breakout", mean_reversion: "Mean-Rev",
  trend_follow: "Trend", volatility_squeeze: "Squeeze",
};
const sLabel = (s?: string) => (s ? STRAT_LABEL[s] ?? s : "—");

export default function Page() {
  const [status, live] = useAgent<Status | null>("/status", null);
  const [positions] = useAgent<Pos[]>("/positions", []);
  const [trades] = useAgent<Trade[]>("/trades", []);
  const [traces] = useAgent<Trace[]>("/traces?limit=40", []);

  const pnl = (status?.realized_pnl_usd ?? 0) + (status?.unrealized_pnl_usd ?? 0);
  const wins = trades.filter((t) => t.pnl_usd > 0).length;
  const winRate = trades.length ? (wins / trades.length) * 100 : 0;
  const exposure = positions.reduce((a, p) => a + p.notional_usd, 0);
  const uni = status?.loop?.universe;
  const markets = status?.loop?.markets ?? uni?.markets ?? uni?.polled ?? uni?.candidates ?? "—";
  const mode = status?.loop?.risk_mode ?? "—";
  const slotsMax = status?.slots_max ?? status?.loop?.risk?.max_positions ?? 5;

  return (
    <>
      <main className="main">
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE · PAPER" : "OFFLINE"}</span>
          <span className={status?.kill_switch_fired ? "pill dead" : "pill"}>
            <span className="dot" />
            {status?.kill_switch_fired ? "Kill Switch Fired" : live ? "Agents Running" : "Connecting…"}
          </span>
          {live && <span className="badge gold" style={{ textTransform: "capitalize" }}>{mode} mode</span>}
        </div>

        <div className="cards">
          <div className="card"><div className="lbl">Portfolio Value</div>
            <div className="val gold">${fmt(status?.equity_usd ?? 0)}</div></div>
          <div className="card"><div className="lbl">P/L</div>
            <div className={pnl >= 0 ? "val pos" : "val neg"}>{pnl >= 0 ? "+" : ""}{fmt(pnl)}</div></div>
          <div className="card"><div className="lbl">Markets</div>
            <div className="val cyan">{markets}</div></div>
          <div className="card"><div className="lbl">Risk Exposure</div>
            <div className="val">${fmt(exposure)}</div></div>
          <div className="card"><div className="lbl">Win Rate</div>
            <div className="val pos">{fmt(winRate)}%</div></div>
          <div className="card"><div className="lbl">Open Positions</div>
            <div className="val">{status?.slots_used ?? 0}/{slotsMax}</div></div>
        </div>

        <h2 className="section">Open Positions</h2>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Market</th><th>Strategy</th><th>TF</th><th>Mode</th><th>Avg Entry</th><th>Size</th>
              <th>Gain</th><th>Peak</th><th>Stop</th><th>Target</th><th>Avg</th></tr></thead>
            <tbody>
              {positions.length === 0 && <tr><td colSpan={11}>no open positions — agents are watching, waiting for full gate confirmation</td></tr>}
              {positions.map((p, i) => (
                <tr key={i}>
                  <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{p.symbol}/USDT</td>
                  <td><span className="badge cyan">{sLabel(p.strategy)}</span></td>
                  <td className="num">{p.tf}</td>
                  <td><span className={p.state === "sl_in_profit" ? "badge green" : "badge gold"}>
                    {p.state === "sl_in_profit" ? "LOCKED GREEN" : "ACTIVE"}</span></td>
                  <td className="num">{fmt(p.avg_entry)}</td>
                  <td className="num">${fmt(p.notional_usd)}</td>
                  <td className={p.gain_pct >= 0 ? "num pos" : "num neg"}>{p.gain_pct >= 0 ? "+" : ""}{p.gain_pct}%</td>
                  <td className="num">+{p.peak_gain_pct}%</td>
                  <td className="num">{p.stop_pct != null ? "+" + p.stop_pct + "%" : "—"}</td>
                  <td className="num">{p.target_pct}%</td>
                  <td className="num">{p.averaging_done}/2</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="section">Recent Decisions</h2>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Time</th><th>Market</th><th>Strategy</th><th>TF</th><th>Decision Trail (Gate Audit)</th><th>Result</th></tr></thead>
            <tbody>
              {traces.length === 0 && <tr><td colSpan={6}>no evaluations yet — markets warming up</td></tr>}
              {[...traces].reverse().slice(0, 12).map((t, i) => (
                <tr key={i}>
                  <td className="num">{new Date(t.ts).toLocaleTimeString()}</td>
                  <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{t.symbol}</td>
                  <td><span className="badge cyan">{sLabel(t.strategy)}</span></td>
                  <td className="num">{t.tf}</td>
                  <td>{t.gates.map((g, j) => (
                    <span key={j} className={g.passed ? "gate ok" : "gate no"} title={g.detail}>
                      {g.step.replace(/_/g, " ")}
                    </span>
                  ))}</td>
                  <td>{t.entered
                    ? <span className="badge green">ENTERED</span>
                    : <span className="badge gray">SKIPPED</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="section">Closed Trades</h2>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Market</th><th>Strategy</th><th>TF</th><th>Exit Reason</th><th>P/L</th><th>Closed</th></tr></thead>
            <tbody>
              {trades.length === 0 && <tr><td colSpan={6}>no closed trades</td></tr>}
              {[...trades].reverse().slice(0, 15).map((t, i) => (
                <tr key={i}>
                  <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{t.symbol}/USDT</td>
                  <td><span className="badge cyan">{sLabel(t.strategy)}</span></td>
                  <td className="num">{t.tf}</td>
                  <td><span className={t.reason === "take_profit" ? "badge green" : t.reason === "kill_switch" ? "badge red" : "badge cyan"}>
                    {t.reason.replace(/_/g, " ").toUpperCase()}</span></td>
                  <td className={t.pnl_usd >= 0 ? "num pos" : "num neg"}>{t.pnl_usd >= 0 ? "+" : ""}{fmt(t.pnl_usd)}</td>
                  <td className="num">{t.closed ? new Date(t.closed).toLocaleString() : "—"}</td>
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
              const lastGate = t.gates[t.gates.length - 1];
              return (
                <div key={i} className={t.entered ? "feed-item entered" : "feed-item blocked"}>
                  <div className="when">{new Date(t.ts).toLocaleTimeString()} — {t.symbol} {t.tf} · {sLabel(t.strategy)}</div>
                  <div className="what">
                    {t.entered
                      ? <><b>Entered long</b> — all gates confirmed, limit filled at level.</>
                      : <><b>Skipped</b> — {lastGate ? (lastGate.detail || lastGate.step.replace(/_/g, " ") + " not confirmed") : "awaiting confirmation"}.</>}
                  </div>
                </div>
              );
            })}
            {traces.length === 0 && <div className="feed-item"><div className="what">Watching markets…</div></div>}
          </div>
        </div>

        <div className="vault">
          <div className="title">🜲 Risk Vault</div>
          <div className="row"><span>Risk Mode</span><span className="v" style={{ textTransform: "capitalize" }}>{mode}</span></div>
          <div className="row"><span>Position Slots</span><span className="v">{status?.slots_used ?? 0} / {slotsMax}</span></div>
          <div className="row"><span>Open Exposure</span><span className="v">${fmt(exposure)}</span></div>
          <div className="row"><span>Aggregate Drawdown</span><span className="v">${fmt(status?.aggregate_drawdown_usd ?? 0)}</span></div>
          <div className="row"><span>Kill Switch</span>
            <span className={status?.kill_switch_fired ? "v danger" : "v"}>
              {status?.kill_switch_fired ? "FIRED" : "Armed"}</span></div>
        </div>
      </aside>
    </>
  );
}
