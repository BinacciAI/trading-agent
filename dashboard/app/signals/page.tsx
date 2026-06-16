"use client";

import { useAgent, fmt } from "../useAgent";

type Signal = {
  symbol: string; tf: string; side: string; level_price: number;
  target_pct: number; level_kind: string; created: string; expires: string;
};

export default function Signals() {
  const [signals, live] = useAgent<Signal[]>("/signals", []);
  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className="badge cyan">{signals.length} PARKED LEVELS</span>
      </div>
      <h2 className="section">Pending Entries</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: 12.5, marginBottom: 12, maxWidth: 720 }}>
        Gates 1–4 confirmed; the agent is waiting for price to touch the exact level (gate 5).
        A signal detected is never a trade executed — if the level isn't touched before expiry, the signal dies unfilled.
      </p>
      <div className="tbl-wrap">
        <table>
          <thead><tr><th>Market</th><th>TF</th><th>Side</th><th>Entry Level</th><th>Level Type</th>
            <th>Target</th><th>Created</th><th>Expires</th></tr></thead>
          <tbody>
            {signals.length === 0 && <tr><td colSpan={8}>no parked levels — no zone has cleared all four pre-gates yet</td></tr>}
            {signals.map((s, i) => (
              <tr key={i}>
                <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{s.symbol}/USDT</td>
                <td className="num">{s.tf}</td>
                <td><span className="badge gold">{s.side.toUpperCase()}</span></td>
                <td className="num">{fmt(s.level_price)}</td>
                <td><span className="badge cyan">{s.level_kind.replace(/_/g, " ").toUpperCase()}</span></td>
                <td className="num">+{s.target_pct}%</td>
                <td className="num">{new Date(s.created).toLocaleTimeString()}</td>
                <td className="num">{new Date(s.expires).toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
