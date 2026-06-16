"use client";

import { useAgent, fmt } from "../useAgent";

type Status = {
  deposit_usd: number; equity_usd: number; realized_pnl_usd: number;
  unrealized_pnl_usd: number; slots_used: number; slots_max: number;
  aggregate_drawdown_usd: number; kill_switch_fired: boolean;
  venue?: string;
};
type Cfg = {
  perps_leverage?: number; perps_target_mult?: number; allow_shorts?: boolean;
  perp_data_source?: string;
  risk?: { max_positions?: number; reserve_pct?: number;
    position_cap_pct_of_deposit?: number; aggregate_drawdown_kill_pct?: number };
};

export default function Risk() {
  const [status, live] = useAgent<Status | null>("/status", null);
  const [cfg] = useAgent<Cfg | null>("/config", null, 8000);
  const ddLimit = (status?.deposit_usd ?? 1000) * (cfg?.risk?.aggregate_drawdown_kill_pct ?? 0.30);
  const ddUsed = status?.aggregate_drawdown_usd ?? 0;
  const ddPct = ddLimit ? Math.min((ddUsed / ddLimit) * 100, 100) : 0;
  const lev = cfg?.perps_leverage;
  const capPct = (cfg?.risk?.position_cap_pct_of_deposit ?? 0.028) * 100;
  const reservePct = (cfg?.risk?.reserve_pct ?? 0.30) * 100;
  const slotsMax = status?.slots_max ?? cfg?.risk?.max_positions ?? 30;
  // ~liquidation distance for a perp = adverse % move that erases margin ≈ 100/leverage
  const liqMovePct = lev && lev > 0 ? 100 / lev : null;

  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className={status?.kill_switch_fired ? "badge red" : "badge gold"}>
          🜲 {status?.kill_switch_fired ? "KILL SWITCH FIRED" : "KILL SWITCH ARMED"}</span>
      </div>

      <h2 className="section">Hard Limits</h2>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        <div className="card">
          <div className="lbl">Reserved Margin</div>
          <div className="val gold">{fmt(reservePct)}%</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            A fixed share of the deposit never trades, under any conditions. Untouchable by design.</p>
        </div>
        <div className="card">
          <div className="lbl">Position Slots</div>
          <div className="val">{status?.slots_used ?? 0} / {slotsMax}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Hard cap on simultaneous positions. Slots return early only when a stop is locked in profit.</p>
        </div>
        <div className="card">
          <div className="lbl">Per-Position Cap</div>
          <div className="val">~{fmt(capPct)}%</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Even fully averaged, one position cannot exceed its deposit-share ceiling.</p>
        </div>
        <div className="card" style={{ borderColor: ddPct > 60 ? "rgba(255,77,77,0.4)" : undefined }}>
          <div className="lbl">Aggregate Drawdown</div>
          <div className={ddPct > 60 ? "val neg" : "val"}>${fmt(ddUsed)}</div>
          <div style={{ marginTop: 8, height: 6, background: "var(--bg-card)", borderRadius: 3, overflow: "hidden", border: "1px solid var(--border-soft)" }}>
            <div style={{ width: `${ddPct}%`, height: "100%", background: ddPct > 60 ? "var(--loss)" : "var(--brand-gold)" }} />
          </div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            {fmt(ddPct)}% of the kill-switch threshold (${fmt(ddLimit)}). At 100%, everything flattens.</p>
        </div>
      </div>

      <h2 className="section">Perps Leverage</h2>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        <div className="card">
          <div className="lbl">Perps Leverage</div>
          <div className="val gold">{lev != null ? `${fmt(lev)}×` : "—"}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Set by risk mode (10× / 25× / 50×). Spot positions are always 1×.</p>
        </div>
        <div className="card" style={{ borderColor: liqMovePct != null && liqMovePct < 3 ? "rgba(255,77,77,0.4)" : undefined }}>
          <div className="lbl">≈ Liquidation Move</div>
          <div className={liqMovePct != null && liqMovePct < 3 ? "val neg" : "val"}>
            {liqMovePct != null ? `~${fmt(liqMovePct)}%` : "—"}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Approx. adverse price move that erases a perp&apos;s margin at this leverage (before fees/funding).
            Higher leverage = tighter tolerance.</p>
        </div>
        <div className="card">
          <div className="lbl">Perp Price Feed</div>
          <div className="val cyan">{cfg?.perp_data_source === "onchain_perp_mark" ? "On-chain mark"
            : cfg?.perp_data_source === "spot_quote_fallback" ? "Spot (fallback)"
            : cfg?.perp_data_source === "spot_quote" ? "Spot quote" : "—"}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Open perps are managed (TP / trailing / kill) against the venue&apos;s on-chain mark — the price
            they would actually liquidate at.</p>
        </div>
        <div className="card">
          <div className="lbl">Direction</div>
          <div className="val">{cfg?.allow_shorts ? "Long + Short" : "Long-only"}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            The perps book trades both ways when shorts are enabled; spot is always long-only.</p>
        </div>
      </div>

      <h2 className="section">Account</h2>
      <div className="vault" style={{ maxWidth: 560 }}>
        <div className="row"><span>Deposit</span><span className="v">${fmt(status?.deposit_usd ?? 0)}</span></div>
        <div className="row"><span>Equity</span><span className="v">${fmt(status?.equity_usd ?? 0)}</span></div>
        <div className="row"><span>Realized P/L</span><span className="v">${fmt(status?.realized_pnl_usd ?? 0)}</span></div>
        <div className="row"><span>Unrealized P/L</span><span className="v">${fmt(status?.unrealized_pnl_usd ?? 0)}</span></div>
        <div className="row"><span>Venue</span><span className="v">{(status?.venue ?? "—").toUpperCase()}</span></div>
        <div className="row"><span>Kill Switch</span>
          <span className={status?.kill_switch_fired ? "v danger" : "v"}>
            {status?.kill_switch_fired ? "FIRED — manual reset required" : "Armed"}</span></div>
      </div>

      <h2 className="section">Doctrine</h2>
      <div className="vault" style={{ maxWidth: 720, borderColor: "var(--border-cyan)" }}>
        <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.7 }}>
          Signal detected ≠ trade executed. Every entry passes reference → zone → filters → macro → level.
          No macro data: fail closed. No fresh reference: fail closed. Kill switch fired: nothing reopens
          without a human. Risk is enforced by the deterministic engine — the AI cannot override it.
        </p>
      </div>
    </main>
  );
}
