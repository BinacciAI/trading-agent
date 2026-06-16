"use client";

import { useAgent } from "../useAgent";

type Status = {
  kill_switch_fired: boolean;
  loop?: {
    running: boolean; polls: number; last_poll: string | null;
    macro_fresh: boolean; venue: string; markets?: number;
    warmup?: {
      tradable_tfs: string[];
      one_minute_bars: Record<string, number>;
      need_bars?: number;
      required_1m?: Record<string, number>;
      deepest_required_1m?: number;
    };
    universe?: { candidates: number; verified_count: number | null };
  };
};
type Chain = {
  sdk: string; installed: boolean; network: string;
  erc8004: { registered: boolean; agent_id: string | null; tx: string | null; auto_register: boolean };
  apex: { standard: string; mounted: boolean; job_endpoint: string; deliverable: string };
  wallet: string | null;
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
  const [chain] = useAgent<Chain | null>("/chain", null, 15000);
  const loop = status?.loop;
  const running = live && !!loop?.running && !status?.kill_switch_fired;

  return (
    <main className="main">
      <div className="toolbar">
        <span className={running ? "badge green" : "badge gray"}>{running ? "ALL SYSTEMS ACTIVE" : "STANDBY"}</span>
        <span className="badge cyan">{loop?.markets ?? loop?.universe?.candidates ?? "—"} MARKETS</span>
        <span className="badge gold">{loop?.warmup?.tradable_tfs?.length ?? 0}/{Object.keys(loop?.warmup?.required_1m ?? {}).length || 6} TIMEFRAMES WARM</span>
      </div>

      <h2 className="section">Analysis Agents — 5 Simulations</h2>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))" }}>
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

      <h2 className="section">BNB Chain Layer — Identity &amp; Commerce (BNB AI Agent SDK)</h2>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <div className="lbl">SDK</div>
            <span className={chain?.installed ? "badge green" : "badge gray"}>{chain?.installed ? "INSTALLED" : "—"}</span>
          </div>
          <div className="val" style={{ fontSize: 16 }}>bnbagent</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 8 }}>Network: <b style={{ color: "var(--text-primary)" }}>{chain?.network ?? "—"}</b></p>
        </div>
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <div className="lbl">ERC-8004 Identity</div>
            <span className={chain?.erc8004?.registered ? "badge green" : "badge gold"}>{chain?.erc8004?.registered ? "REGISTERED" : "PENDING"}</span>
          </div>
          <div className="val cyan" style={{ fontSize: 16 }}>{chain?.erc8004?.agent_id ?? "agent #—"}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 8 }}>
            On-chain agent identity. Auto-register: {chain?.erc8004?.auto_register ? "on" : "off"}.
          </p>
        </div>
        <div className="card" style={{ borderColor: "var(--border-cyan)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <div className="lbl">APEX Commerce</div>
            <span className={chain?.apex?.mounted ? "badge green" : "badge gray"}>{chain?.apex?.mounted ? "MOUNTED" : "—"}</span>
          </div>
          <div className="val" style={{ fontSize: 16 }}>{chain?.apex?.standard ?? "ERC-8183"}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 8 }}>
            Agents pay (escrowed) for strategy specs at <code style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{chain?.apex?.job_endpoint ?? "/apex/job/execute"}</code>.
          </p>
        </div>
        <div className="card">
          <div className="lbl">Wallet</div>
          <div className="val" style={{ fontSize: 13, fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>
            {chain?.wallet ? `${chain.wallet.slice(0, 10)}…${chain.wallet.slice(-6)}` : "self-custody (TWAK)"}
          </div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 8 }}>Keys sign locally — the agent never holds them.</p>
        </div>
      </div>

      <h2 className="section">Warmup — Agent Intake Coverage</h2>
      {(() => {
        const w = loop?.warmup;
        const req = w?.required_1m ?? {};
        const tfs = Object.entries(req).sort((a, b) => a[1] - b[1]); // [tf, bars] asc
        const deepest = w?.deepest_required_1m ?? (tfs.length ? tfs[tfs.length - 1][1] : 0);
        const need = w?.need_bars ?? 60;
        const largestTf = tfs.length ? tfs[tfs.length - 1][0] : "—";
        const rows = Object.entries(w?.one_minute_bars ?? {}).sort((a, b) => b[1] - a[1]);
        return (
          <>
            <p className="lede" style={{ marginBottom: 12 }}>
              Each agent needs <b style={{ color: "var(--text-primary)" }}>{need} bars</b> of
              context per timeframe. A market is fully warm only once its one-minute history
              clears the <b style={{ color: "var(--text-primary)" }}>deepest</b> intake —{" "}
              <b style={{ color: "var(--brand-gold)" }}>{deepest.toLocaleString()} bars</b> ({need} × {largestTf}).
              Each tick below marks one timeframe&apos;s intake; the fill pushes past them as history accrues.
            </p>
            <div className="tbl-wrap">
              <table>
                <thead><tr>
                  <th>Market</th><th className="num">1m Bars</th>
                  <th>Coverage vs Deepest Intake</th><th>Timeframes Warm</th><th>Status</th>
                </tr></thead>
                <tbody>
                  {!w?.one_minute_bars && <tr><td colSpan={5} className="empty">connecting…</td></tr>}
                  {rows.map(([sym, bars]) => {
                    const pct = deepest ? Math.min(bars / deepest, 1) * 100 : 0;
                    const exceed = deepest > 0 && bars >= deepest;
                    const mult = deepest ? bars / deepest : 0;
                    const warm = tfs.filter(([, r]) => bars >= r).length;
                    return (
                      <tr key={sym}>
                        <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{sym}</td>
                        <td className="num">{bars.toLocaleString()}</td>
                        <td>
                          <div className={exceed ? "cov exceed" : "cov"}>
                            <div className="cov-track">
                              <div className="cov-fill" style={{ width: `${pct}%` }} />
                              {tfs.map(([tf, r]) => (
                                <span key={tf} className={bars >= r ? "cov-tick lit" : "cov-tick"}
                                      style={{ left: `${Math.min(r / deepest, 1) * 100}%` }}
                                      title={`${tf} · ${r.toLocaleString()} bars`} />
                              ))}
                            </div>
                            <span className="cov-num">{exceed ? `×${mult.toFixed(1)}` : `${Math.round(pct)}%`}</span>
                          </div>
                        </td>
                        <td>
                          <div className="tfpills">
                            {tfs.map(([tf, r]) => (
                              <span key={tf} className={bars >= r ? "tfpill warm" : "tfpill"}>{tf}</span>
                            ))}
                            <span className="tfpill-count">{warm}/{tfs.length}</span>
                          </div>
                        </td>
                        <td><span className={exceed ? "badge green" : "badge gold"}>
                          {exceed ? "ALL AGENTS WARM" : "WARMING"}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        );
      })()}
    </main>
  );
}
