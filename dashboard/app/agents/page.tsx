"use client";

import { useAgent } from "../useAgent";

type Status = {
  kill_switch_fired: boolean;
  loop?: {
    running: boolean; polls: number; last_poll: string | null;
    macro_fresh: boolean; venue: string;
    warmup?: { tradable_tfs: string[]; one_minute_bars: Record<string, number> };
    universe?: { candidates: number; verified_count: number | null };
  };
};

const SIMS = [
  { name: "Cold Start", code: "SIM 01", role: "Replays history on boot so every market has a fresh reference point before any entry is considered.", cadence: "Once · at startup" },
  { name: "Reference Keeper", code: "SIM 02", role: "Continuously refreshes reference anchors: Fibonacci structures, candles, divergences, local extrema.", cadence: "Continuous · background" },
  { name: "Clean Anchor", code: "SIM 03", role: "Maintains undistorted entry-grade references — indicator context is recorded but never vetoes the anchor.", cadence: "Continuous · background" },
  { name: "Zone Scout", code: "SIM A", role: "Decides whether price is in a zone where opening is allowed at all, then runs the confirmation filter set.", cadence: "Every completed bar" },
  { name: "Level Sniper", code: "SIM B", role: "Picks the exact level to enter at — log S/R, Fib pivots, retracements, channels. Always limit-at-level.", cadence: "Every completed bar" },
];

export default function Agents() {
  const [status, live] = useAgent<Status | null>("/status", null);
  const loop = status?.loop;
  const running = live && !!loop?.running && !status?.kill_switch_fired;

  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className={running ? "badge green" : "badge gray"}>{running ? "ALL SYSTEMS ACTIVE" : "STANDBY"}</span>
        <span className="badge cyan">{loop?.universe?.verified_count ?? loop?.universe?.candidates ?? "—"} MARKETS</span>
        <span className="badge gold">{loop?.warmup?.tradable_tfs?.length ?? 0}/4 TIMEFRAMES WARM</span>
      </div>

      <h2 className="section">Analysis Agents — 5 Simulations</h2>
      <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))" }}>
        {SIMS.map((s) => (
          <div key={s.code} className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <div className="lbl">{s.code}</div>
              <span className={running ? "badge green" : "badge gray"}>{running ? "ACTIVE" : "IDLE"}</span>
            </div>
            <div className="val" style={{ fontSize: 18 }}>{s.name}</div>
            <p style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 8, lineHeight: 1.55 }}>{s.role}</p>
            <div style={{ marginTop: 10, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>{s.cadence}</div>
          </div>
        ))}
        <div className="card" style={{ borderColor: "var(--border-cyan)" }}>
          <div className="lbl">EXECUTOR</div>
          <div className="val cyan" style={{ fontSize: 18 }}>Risk Engine</div>
          <p style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 8, lineHeight: 1.55 }}>
            Deterministic execution: reserved margin, slot caps, trailing stops, kill switch.
            The AI never decides — it executes what the gates confirm.
          </p>
          <div style={{ marginTop: 10, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
            venue: {loop?.venue ?? "—"} · polls: {loop?.polls ?? 0}
          </div>
        </div>
      </div>

      <h2 className="section">Warmup — 1m Bars Collected Per Market</h2>
      <div className="tbl-wrap">
        <table>
          <thead><tr><th>Market</th><th>1m Bars</th><th>Readiness</th></tr></thead>
          <tbody>
            {!loop?.warmup?.one_minute_bars && <tr><td colSpan={3}>connecting…</td></tr>}
            {Object.entries(loop?.warmup?.one_minute_bars ?? {})
              .sort((a, b) => b[1] - a[1]).slice(0, 30).map(([sym, bars]) => (
              <tr key={sym}>
                <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{sym}</td>
                <td className="num">{bars}</td>
                <td><span className={bars >= 84 ? "badge green" : "badge gray"}>
                  {bars >= 84 ? "3M READY" : "WARMING"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
