"use client";

import { useEffect, useState } from "react";
import { useAgent, fmt } from "../useAgent";
import { AttributionBars } from "../charts";

type Book = { open: number; long: number; short: number; realized: number };
type Status = {
  equity_usd?: number; realized_pnl_usd?: number; unrealized_pnl_usd?: number;
  slots_used?: number; slots_max?: number; kill_switch_fired?: boolean;
  regime?: string; regime_weighting?: boolean; books?: { spot: Book; perp: Book };
  loop?: { markets?: number };
};
type Cfg = {
  perps_leverage?: number; min_signal_strength?: number; regime_weighting?: boolean;
  perps_target_mult?: number; trailing?: { trigger: number; initial: number; step: number };
  trading_halted?: boolean; halt_reason?: string; risk?: { risk_mode?: string; max_positions?: number };
  risk_modes?: string[];
};
type AttrRow = { trades: number; wins: number; realized: number; unrealized: number; net: number; open: number; win_rate: number };
type Attr = { regime?: string; by_strategy: Record<string, AttrRow>; by_book: Record<string, AttrRow>; by_regime: Record<string, AttrRow> };
type Trade = { symbol: string; strategy?: string; market?: string; reason: string; pnl_usd: number; closed: string | null };

const REG: Record<string, string> = { risk_on: "badge green", chop: "badge gold", risk_off: "badge red", unknown: "badge gray" };
const sl = (s: string) => s.replace(/_/g, " ");

async function postAgent(path: string) {
  try { const r = await fetch(`/agent${path}`, { method: "POST" }); return await r.json(); } catch { return null; }
}

export default function Console() {
  const [status] = useAgent<Status>("/status", {}, 4000);
  const [cfg] = useAgent<Cfg>("/config", {}, 8000);
  const [attr] = useAgent<Attr>("/attribution", { by_strategy: {}, by_book: {}, by_regime: {} }, 6000);
  const [trades] = useAgent<Trade[]>("/trades", [], 8000);

  const [lev, setLev] = useState("");
  const [str, setStr] = useState("");
  const [tgt, setTgt] = useState("");
  const [trg, setTrg] = useState("");
  const [ini, setIni] = useState("");
  const [stp, setStp] = useState("");
  const [rw, setRw] = useState<boolean | null>(null);
  const [msg, setMsg] = useState("");
  const [synced, setSynced] = useState(false);

  // seed controls from live config once
  useEffect(() => {
    if (synced || cfg.perps_leverage == null) return;
    setLev(String(cfg.perps_leverage));
    setStr(String(cfg.min_signal_strength ?? 0));
    setTgt(String(cfg.perps_target_mult ?? 2));
    setTrg(String(cfg.trailing?.trigger ?? 0.4));
    setIni(String(cfg.trailing?.initial ?? 0.2));
    setStp(String(cfg.trailing?.step ?? 0.1));
    setRw(cfg.regime_weighting ?? true);
    setSynced(true);
  }, [cfg, synced]);

  const halted = cfg.trading_halted;
  const regime = status.regime ?? "unknown";
  const realized = status.realized_pnl_usd ?? 0;
  const unreal = status.unrealized_pnl_usd ?? 0;
  const exposure = (status.books ? status.books.spot.open + status.books.perp.open : 0);

  const apply = async () => {
    const q = new URLSearchParams();
    if (lev) q.set("perps_leverage", lev);
    if (str !== "") q.set("min_strength", str);
    if (tgt) q.set("perps_target_mult", tgt);
    if (trg) q.set("trail_trigger", trg);
    if (ini) q.set("trail_initial", ini);
    if (stp) q.set("trail_step", stp);
    if (rw != null) q.set("regime_weighting", String(rw));
    const r = await fetch(`/agent/control?${q.toString()}`, { method: "POST" });
    const j = await r.json();
    setMsg(j?.ok ? `Applied ${Object.keys(j.applied || {}).length} change(s) to the live engine.` : "Apply failed.");
    setTimeout(() => setMsg(""), 4000);
  };
  const setMode = async (m: string) => { const j = await postAgent(`/risk/mode?mode=${m}`); setMsg(j?.ok ? `Risk mode → ${m}` : "failed"); setTimeout(() => setMsg(""), 3500); };
  const doHalt = async () => { await postAgent("/halt?reason=operator%20stop"); setMsg("Trading halted — new opens blocked."); setTimeout(() => setMsg(""), 4000); };
  const doResume = async () => { await postAgent("/venue/resume"); setMsg("Trading resumed."); setTimeout(() => setMsg(""), 3500); };

  const alerts = [...trades].reverse().filter((t) => t.reason === "hard_stop" || t.reason === "kill_switch").slice(0, 8);
  const mode = cfg.risk?.risk_mode ?? "—";

  const attrTable = (title: string, g: Record<string, AttrRow>) => (
    <>
      <h2 className="section">{title}</h2>
      <div className="tbl-wrap short">
        <table>
          <thead><tr><th>Bucket</th><th className="num">Trades</th><th className="num">Win</th>
            <th className="num">Open</th><th className="num">Realized</th><th className="num">Unreal</th><th className="num">Net</th></tr></thead>
          <tbody>
            {Object.keys(g).length === 0 && <tr><td colSpan={7} className="empty">no data yet</td></tr>}
            {Object.entries(g).sort((a, b) => b[1].net - a[1].net).map(([k, r]) => (
              <tr key={k}>
                <td className="mkt">{sl(k)}</td>
                <td className="num dim">{r.trades}</td>
                <td className="num dim">{r.trades ? fmt(r.win_rate) + "%" : "—"}</td>
                <td className="num dim">{r.open}</td>
                <td className={r.realized >= 0 ? "num pos" : "num neg"}>{r.realized >= 0 ? "+" : ""}{fmt(r.realized)}</td>
                <td className={r.unrealized >= 0 ? "num pos" : "num neg"}>{r.unrealized >= 0 ? "+" : ""}{fmt(r.unrealized)}</td>
                <td className={r.net >= 0 ? "num pos" : "num neg"}>{r.net >= 0 ? "+" : ""}{fmt(r.net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );

  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <span className="badge cyan">⚙ OPERATOR CONSOLE</span>
        <span className={REG[regime] || "badge gray"}>REGIME · {regime.toUpperCase().replace("_", "-")}</span>
        <span className={halted ? "badge red" : "badge green"}>{halted ? "HALTED" : "TRADING"}</span>
        {status.kill_switch_fired && <span className="badge red">KILL SWITCH FIRED</span>}
        <span style={{ flex: 1 }} />
        {halted
          ? <button className="btn btn-secondary" onClick={doResume}>Resume</button>
          : <button className="btn btn-danger" onClick={doHalt}>◼ Halt new opens</button>}
      </div>
      {msg && <div className="demo-note">{msg}</div>}

      <div className="statline">
        <span>Equity <b className="gold">${fmt(status.equity_usd ?? 0)}</b></span>
        <span>Net <b className={realized + unreal >= 0 ? "pos" : "neg"}>{realized + unreal >= 0 ? "+" : ""}{fmt(realized + unreal)}</b></span>
        <span>Open <b>{status.slots_used ?? 0}/{status.slots_max ?? 0}</b></span>
        <span>Mode <b className="cyan" style={{ textTransform: "capitalize" }}>{mode}</b></span>
        <span>Leverage <b>{cfg.perps_leverage ?? "—"}×</b></span>
      </div>

      <h2 className="section">Live Controls</h2>
      <div className="vault" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
          {(cfg.risk_modes ?? ["conservative", "balanced", "aggressive"]).map((m) => (
            <button key={m} className={mode === m ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setMode(m)}
              style={{ textTransform: "capitalize" }}>{m}</button>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12 }}>
          <Ctl label="Perps leverage" v={lev} set={setLev} step="1" />
          <Ctl label="Strength gate (0–1)" v={str} set={setStr} step="0.05" />
          <Ctl label="Perp TP mult" v={tgt} set={setTgt} step="0.25" />
          <Ctl label="Trail trigger %" v={trg} set={setTrg} step="0.05" />
          <Ctl label="Trail initial %" v={ini} set={setIni} step="0.02" />
          <Ctl label="Trail step %" v={stp} set={setStp} step="0.01" />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 14, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-secondary)", cursor: "pointer" }}>
            <input type="checkbox" checked={!!rw} onChange={(e) => setRw(e.target.checked)} />
            Regime-weighted allocation
          </label>
          <span style={{ flex: 1 }} />
          <button className="btn btn-primary" onClick={apply}>Apply to engine</button>
        </div>
      </div>

      <h2 className="section">Net P/L by Strategy</h2>
      <div className="chartbox" style={{ marginBottom: 20 }}>
        <AttributionBars rows={Object.entries(attr.by_strategy).map(([label, r]) => ({ label, net: r.net }))}
          empty="no closed/open P/L yet" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>{attrTable("by Book", attr.by_book)}</div>
        <div>{attrTable("by Regime", attr.by_regime)}</div>
      </div>

      <h2 className="section">Risk Alerts</h2>
      <div className="tbl-wrap short">
        <table>
          <thead><tr><th>Market</th><th>Strategy</th><th>Event</th><th className="num">P/L</th><th className="num">When</th></tr></thead>
          <tbody>
            {alerts.length === 0 && <tr><td colSpan={5} className="empty">no stops or kills — book is healthy</td></tr>}
            {alerts.map((t, i) => (
              <tr key={i}>
                <td className="mkt">{t.symbol}<span className="quote">/USDT</span></td>
                <td><span className="badge cyan">{sl(t.strategy ?? "reaction")}</span></td>
                <td><span className="badge red">{sl(t.reason).toUpperCase()}</span></td>
                <td className={t.pnl_usd >= 0 ? "num pos" : "num neg"}>{t.pnl_usd >= 0 ? "+" : ""}{fmt(t.pnl_usd)}</td>
                <td className="num dim">{t.closed ? new Date(t.closed).toLocaleTimeString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

function Ctl({ label, v, set, step }: { label: string; v: string; set: (s: string) => void; step: string }) {
  return (
    <div className="sel-wrap">
      <span className="sel-lbl">{label}</span>
      <input type="number" step={step} value={v} onChange={(e) => set(e.target.value)}
        style={{
          background: "var(--bg-card)", border: "1px solid var(--border-soft)", borderRadius: "var(--radius-md)",
          color: "var(--text-primary)", padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 13, outline: "none",
        }} />
    </div>
  );
}
