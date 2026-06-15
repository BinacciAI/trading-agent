"use client";

import { useAgent, useAgentText, fmt } from "../useAgent";

type Ref = { symbol: string; tf: string; kind: string; price: number; ts: string; clean: boolean };
type StratStat = { wins: number; losses: number; trades: number; win_rate: number; pnl: number };
type Mem = {
  identity: string;
  equity_usd: number; realized_pnl_usd: number;
  open_positions: number; closed_trades: number;
  per_strategy: Record<string, StratStat>;
  lessons: string[];
  references: Ref[];
  chart_memory: { symbols_with_data: number; max_bars: number; retention_bars: number };
};
type Book = { open: number; long: number; short: number; realized: number };
type Status = { books?: { spot: Book; perp: Book }; trade_mode?: string };

const EMPTY: Mem = {
  identity: "", equity_usd: 0, realized_pnl_usd: 0, open_positions: 0, closed_trades: 0,
  per_strategy: {}, lessons: [], references: [],
  chart_memory: { symbols_with_data: 0, max_bars: 0, retention_bars: 0 },
};

export default function Memory() {
  const [mem, live] = useAgent<Mem>("/memory", EMPTY);
  const [md] = useAgentText("/memory/md");
  const [status] = useAgent<Status>("/status", {});
  const [cfg] = useAgent<{ perps_leverage?: number }>("/config", {});
  const lev = cfg.perps_leverage ?? 2;
  const books = status.books;
  const cm = mem.chart_memory || EMPTY.chart_memory;
  const days = (cm.retention_bars / 1440).toFixed(1);
  const strats = Object.entries(mem.per_strategy || {});

  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className="badge cyan">🧠 PERSISTENT BRAIN</span>
        <span className="badge gold">NOTHING EVER FORGOTTEN</span>
      </div>
      <h2 className="section">Binacci's Memory — Brain, Consciousness & Soul</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: 12.5, marginBottom: 16, maxWidth: 760 }}>
        Three durable memory layers persist on the volume across every restart and redeploy.
        The agent writes its own MEMORY.md each checkpoint — identity, regime, positions, and
        auto-distilled lessons. It wakes up knowing every level it has ever traded from.
      </p>

      {/* three memory layers */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
        <Layer title="Chart Memory" tone="cyan"
          lines={[`${cm.symbols_with_data} symbols with live data`,
                  `up to ${fmt(cm.max_bars)} 1m bars each`,
                  `~${days}d retention · restored warm`]} />
        <Layer title="Market Memory" tone="gold"
          lines={[`${(mem.references || []).length} reference levels`,
                  `extrema · fib · divergence anchors`,
                  `survives restarts — never re-derived`]} />
        <Layer title="Self Memory" tone="green"
          lines={[`${mem.closed_trades} trades remembered`,
                  `${(mem.lessons || []).length} lessons distilled`,
                  `MEMORY.md rewritten each checkpoint`]} />
      </div>

      {/* spot + perps books, side by side */}
      {books && (
        <>
          <h2 className="section">Two Books, One Brain — Spot &amp; Perps at Once</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            <BookCard label="SPOT BOOK" sub="PancakeSwap · long-only" tone="green" b={books.spot} />
            <BookCard label="PERPS BOOK" sub={`on-chain perps · long + short · ${lev}x`} tone="cyan" b={books.perp} both />
          </div>
        </>
      )}

      {/* lessons learned */}
      <h2 className="section">Lessons Learned</h2>
      <div className="tbl-wrap" style={{ marginBottom: 20 }}>
        <ul style={{ margin: 0, padding: "10px 22px", color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.9 }}>
          {(mem.lessons || []).map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      </div>

      {/* per-strategy memory */}
      {strats.length > 0 && (
        <>
          <h2 className="section">Per-Strategy Performance Memory</h2>
          <div className="tbl-wrap" style={{ marginBottom: 20 }}>
            <table>
              <thead><tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>Realized P/L</th></tr></thead>
              <tbody>
                {strats.map(([name, s]) => (
                  <tr key={name}>
                    <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{name.replace(/_/g, " ")}</td>
                    <td className="num">{s.trades}</td>
                    <td className="num">{fmt(s.win_rate)}%</td>
                    <td className="num" style={{ color: s.pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                      {s.pnl >= 0 ? "+" : ""}{fmt(s.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* reference levels */}
      <h2 className="section">Reference Levels — What It Trades Reactions From</h2>
      <div className="tbl-wrap" style={{ marginBottom: 20 }}>
        <table>
          <thead><tr><th>Market</th><th>TF</th><th>Anchor</th><th>Price</th><th>Set At</th><th>Pipeline</th></tr></thead>
          <tbody>
            {(mem.references || []).length === 0 &&
              <tr><td colSpan={6}>building reference memory…</td></tr>}
            {(mem.references || []).map((r, i) => (
              <tr key={i}>
                <td style={{ color: "var(--text-primary)", fontWeight: 600 }}>{r.symbol}</td>
                <td className="num">{r.tf}</td>
                <td><span className={r.kind === "divergence" ? "badge cyan" : "badge gold"}>
                  {r.kind.replace(/_/g, " ").toUpperCase()}</span></td>
                <td className="num">{fmt(r.price)}</td>
                <td className="num">{new Date(r.ts).toLocaleString()}</td>
                <td><span className={r.clean ? "badge green" : "badge gray"}>{r.clean ? "CLEAN" : "STANDARD"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* the soul — raw MEMORY.md the agent writes about itself */}
      <h2 className="section">MEMORY.md — The Agent's Own Words</h2>
      <pre style={{
        background: "var(--bg-elevated, #0d1117)", border: "1px solid var(--border, #232a36)",
        borderRadius: 10, padding: "18px 20px", overflow: "auto", maxHeight: 540,
        fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)", fontSize: 12.5,
        lineHeight: 1.7, color: "var(--text-secondary)", whiteSpace: "pre-wrap",
      }}>{md || "loading the brain…"}</pre>
    </main>
  );
}

function Layer({ title, lines, tone }: { title: string; lines: string[]; tone: string }) {
  return (
    <div style={{ background: "var(--bg-card, #11161f)", border: "1px solid var(--border, #232a36)",
      borderRadius: 10, padding: 16 }}>
      <div className={`badge ${tone}`} style={{ marginBottom: 10 }}>{title}</div>
      {lines.map((l, i) => (
        <div key={i} style={{ color: i === 0 ? "var(--text-primary)" : "var(--text-secondary)",
          fontSize: i === 0 ? 14 : 12.5, fontWeight: i === 0 ? 700 : 400, marginTop: i ? 4 : 0 }}>{l}</div>
      ))}
    </div>
  );
}

function BookCard({ label, sub, b, tone, both }: {
  label: string; sub: string; b: Book; tone: string; both?: boolean;
}) {
  return (
    <div style={{ background: "var(--bg-card, #11161f)", border: "1px solid var(--border, #232a36)",
      borderRadius: 10, padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className={`badge ${tone}`}>{label}</span>
        <span style={{ color: b.realized >= 0 ? "var(--green)" : "var(--red)", fontWeight: 700 }}>
          {b.realized >= 0 ? "+" : ""}{fmt(b.realized)} USD
        </span>
      </div>
      <div style={{ color: "var(--text-secondary)", fontSize: 11.5, marginTop: 4 }}>{sub}</div>
      <div style={{ display: "flex", gap: 18, marginTop: 12, fontSize: 13 }}>
        <span style={{ color: "var(--text-primary)", fontWeight: 700 }}>{b.open} open</span>
        <span style={{ color: "var(--green)" }}>{b.long} long</span>
        {both && <span style={{ color: "var(--red)" }}>{b.short} short</span>}
      </div>
    </div>
  );
}
