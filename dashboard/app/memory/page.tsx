"use client";

import { useAgent, fmt } from "../useAgent";

type Ref = {
  symbol: string; tf: string; kind: string; price: number; ts: string;
  clean: boolean; rsi: number | null; volume_ratio: number | null;
};

export default function Memory() {
  const [refs, live] = useAgent<Ref[]>("/references", []);
  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className="badge cyan">❖ {refs.length} REFERENCE POINTS</span>
      </div>
      <h2 className="section">Market Memory — What the Agent Trades Reactions From</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: 12.5, marginBottom: 12, maxWidth: 720 }}>
        Reference points are the anchors maintained 24/7 by the background simulations:
        local extrema, Fibonacci structures, and divergence pivots. The next entry is always
        searched relative to these — never guessed from a prompt.
      </p>
      <div className="tbl-wrap">
        <table>
          <thead><tr><th>Market</th><th>TF</th><th>Anchor Type</th><th>Price</th>
            <th>Set At</th><th>Pipeline</th><th>RSI Context</th><th>Vol Ratio</th></tr></thead>
          <tbody>
            {refs.length === 0 && <tr><td colSpan={8}>no references yet — background simulations are warming up</td></tr>}
            {refs.map((r, i) => (
              <tr key={i}>
                <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{r.symbol}</td>
                <td className="num">{r.tf}</td>
                <td><span className={r.kind === "divergence" ? "badge cyan" : "badge gold"}>
                  {r.kind.replace(/_/g, " ").toUpperCase()}</span></td>
                <td className="num">{fmt(r.price)}</td>
                <td className="num">{new Date(r.ts).toLocaleString()}</td>
                <td><span className={r.clean ? "badge green" : "badge gray"}>{r.clean ? "CLEAN" : "STANDARD"}</span></td>
                <td className="num">{r.rsi != null ? fmt(r.rsi) : "—"}</td>
                <td className="num">{r.volume_ratio != null ? fmt(r.volume_ratio) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
