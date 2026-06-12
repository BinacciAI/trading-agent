"use client";

import { useEffect, useState } from "react";

type Status = {
  deposit_usd: number; realized_pnl_usd: number; unrealized_pnl_usd: number;
  equity_usd: number; open_positions: number; slots_used: number; slots_max: number;
  aggregate_drawdown_usd: number; kill_switch_fired: boolean; closed_trades: number;
};
type Pos = {
  symbol: string; tf: string; side: string; state: string; avg_entry: number;
  notional_usd: number; gain_pct: number; peak_gain_pct: number;
  stop_pct: number | null; target_pct: number; averaging_done: number;
};
type Trade = { symbol: string; tf: string; pnl_usd: number; reason: string; closed: string | null };
type Trace = {
  symbol: string; tf: string; ts: string; entered: boolean;
  gates: { step: string; passed: boolean; detail: string }[];
};

const fmt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });

export default function Page() {
  const [status, setStatus] = useState<Status | null>(null);
  const [positions, setPositions] = useState<Pos[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    const tick = async () => {
      try {
        const [s, p, t, tr] = await Promise.all([
          fetch("/agent/status").then((r) => r.json()),
          fetch("/agent/positions").then((r) => r.json()),
          fetch("/agent/trades").then((r) => r.json()),
          fetch("/agent/traces?limit=20").then((r) => r.json()),
        ]);
        setStatus(s); setPositions(p); setTrades(t); setTraces(tr); setErr("");
      } catch {
        setErr("agent API unreachable — start it with: binacci serve");
      }
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => clearInterval(id);
  }, []);

  const pnl = (status?.realized_pnl_usd ?? 0) + (status?.unrealized_pnl_usd ?? 0);

  return (
    <main className="wrap">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Binacci <span className="g">Agent</span></h1>
        <span className="pill"><span className="dot" />
          {status?.kill_switch_fired ? "KILL SWITCH" : "running"}
        </span>
      </div>

      {err && <p className="err">{err}</p>}

      <div className="cards">
        <div className="card"><div className="lbl">Equity</div>
          <div className="val cy">${fmt(status?.equity_usd ?? 0)}</div></div>
        <div className="card"><div className="lbl">PnL</div>
          <div className={`val ${pnl >= 0 ? "pos" : "neg"}`}>{pnl >= 0 ? "+" : ""}{fmt(pnl)}</div></div>
        <div className="card"><div className="lbl">Slots</div>
          <div className="val">{status?.slots_used ?? 0}/{status?.slots_max ?? 5}</div></div>
        <div className="card"><div className="lbl">Aggregate DD</div>
          <div className="val">${fmt(status?.aggregate_drawdown_usd ?? 0)}</div></div>
        <div className="card"><div className="lbl">Closed Trades</div>
          <div className="val">{status?.closed_trades ?? 0}</div></div>
      </div>

      <h2>Open Positions</h2>
      <table>
        <thead><tr><th>Symbol</th><th>TF</th><th>State</th><th>Avg Entry</th><th>Notional</th>
          <th>Gain %</th><th>Peak %</th><th>SL @</th><th>Target %</th><th>Avg #</th></tr></thead>
        <tbody>
          {positions.length === 0 && <tr><td colSpan={10}>no open positions</td></tr>}
          {positions.map((p, i) => (
            <tr key={i}>
              <td>{p.symbol}</td><td>{p.tf}</td><td>{p.state}</td>
              <td>{fmt(p.avg_entry)}</td><td>${fmt(p.notional_usd)}</td>
              <td className={p.gain_pct >= 0 ? "val pos" : "val neg"} style={{ fontSize: 13 }}>
                {p.gain_pct >= 0 ? "+" : ""}{p.gain_pct}%</td>
              <td>+{p.peak_gain_pct}%</td>
              <td>{p.stop_pct != null ? `+${p.stop_pct}%` : "—"}</td>
              <td>{p.target_pct}%</td><td>{p.averaging_done}/2</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Decision Traces — 5-Gate Audit</h2>
      <table>
        <thead><tr><th>Time</th><th>Symbol</th><th>TF</th><th>Gates</th><th>Entered</th></tr></thead>
        <tbody>
          {traces.length === 0 && <tr><td colSpan={5}>no evaluations yet</td></tr>}
          {[...traces].reverse().map((t, i) => (
            <tr key={i}>
              <td>{new Date(t.ts).toLocaleTimeString()}</td>
              <td>{t.symbol}</td><td>{t.tf}</td>
              <td>{t.gates.map((g, j) => (
                <span key={j} className={`gate ${g.passed ? "ok" : "no"}`} title={g.detail}>
                  {g.step.replace(/_/g, " ")}
                </span>
              ))}</td>
              <td>{t.entered ? "✓" : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Closed Trades</h2>
      <table>
        <thead><tr><th>Symbol</th><th>TF</th><th>Reason</th><th>PnL</th><th>Closed</th></tr></thead>
        <tbody>
          {trades.length === 0 && <tr><td colSpan={5}>no closed trades</td></tr>}
          {[...trades].reverse().slice(0, 30).map((t, i) => (
            <tr key={i}>
              <td>{t.symbol}</td><td>{t.tf}</td><td>{t.reason}</td>
              <td className={t.pnl_usd >= 0 ? "val pos" : "val neg"} style={{ fontSize: 13 }}>
                {t.pnl_usd >= 0 ? "+" : ""}{fmt(t.pnl_usd)}</td>
              <td>{t.closed ? new Date(t.closed).toLocaleString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
