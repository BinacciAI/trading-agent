"use client";

import { useAgent, fmt, isRealTx, shortTx } from "../useAgent";

type Trace = {
  symbol: string; tf: string; ts: string; entered: boolean;
  gates: { step: string; passed: boolean; detail: string }[];
};
type VenueInfo = {
  venue: string; testnet: boolean; wallet: string; explorer_tx_base?: string;
  log: { ts: string; action: string; symbol: string; ok: boolean; tx?: string; detail?: string; reason?: string }[];
};

export default function Logs() {
  const [traces, live] = useAgent<Trace[]>("/traces?limit=200", []);
  const [venue] = useAgent<VenueInfo | null>("/venue", null);
  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className="badge gold">{traces.length} EVALUATIONS</span>
        <span className="badge cyan">VENUE: {(venue?.venue ?? "—").toUpperCase()}</span>
      </div>

      <h2 className="section">On-Chain Execution Log</h2>
      <div className="tbl-wrap">
        <table>
          <thead><tr><th>Time</th><th>Action</th><th>Market</th><th>Status</th><th>Tx / Detail</th></tr></thead>
          <tbody>
            {(venue?.log ?? []).length === 0 && <tr><td colSpan={5}>no venue executions — paper mode or no fills yet</td></tr>}
            {[...(venue?.log ?? [])].reverse().map((l, i) => (
              <tr key={i}>
                <td className="num">{new Date(l.ts).toLocaleTimeString()}</td>
                <td><span className={l.action === "open" ? "badge gold" : "badge cyan"}>{l.action.toUpperCase()}</span></td>
                <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{l.symbol}</td>
                <td><span className={l.ok ? "badge green" : "badge red"}>{l.ok ? "OK" : "FAILED"}</span></td>
                <td className="num" style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {isRealTx(l.tx) ? (
                    <a className="txlink" href={`${venue?.explorer_tx_base ?? "https://bscscan.com/tx/"}${l.tx}`}
                       target="_blank" rel="noopener noreferrer" title={l.tx}>{shortTx(l.tx)} ↗</a>
                  ) : (l.tx || l.detail || l.reason || "—")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="section">Decision Audit</h2>
      <div className="tbl-wrap">
        <table>
          <thead><tr><th>Time</th><th>Market</th><th>TF</th><th>Decision Trail</th><th>Blocking Reason</th><th>Result</th></tr></thead>
          <tbody>
            {traces.length === 0 && <tr><td colSpan={6}>no evaluations yet — markets warming up</td></tr>}
            {[...traces].reverse().map((t, i) => {
              const blocker = t.gates.find((g) => !g.passed);
              return (
                <tr key={i}>
                  <td className="num">{new Date(t.ts).toLocaleTimeString()}</td>
                  <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{t.symbol}</td>
                  <td className="num">{t.tf}</td>
                  <td>{t.gates.map((g, j) => (
                    <span key={j} className={g.passed ? "gate ok" : "gate no"} title={g.detail}>
                      {g.step.replace(/_/g, " ")}
                    </span>
                  ))}</td>
                  <td style={{ fontSize: 11.5, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {t.entered ? "—" : (blocker?.detail || "—")}</td>
                  <td>{t.entered
                    ? <span className="badge green">ENTERED</span>
                    : <span className="badge gray">SKIPPED</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
