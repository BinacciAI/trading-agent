"""Track 2 — CMC Strategy Skill: backtestable strategy spec generation.

The skill takes market data (CMC signals) and emits a *backtestable spec*:
a machine-readable description of the Binacci entry chain, execution
parameters, current levels, and a verification backtest — not a live agent.

Spec format follows "quant research" expectations:
* `strategy`     — rules, parameters, gates (deterministic, replayable)
* `market_state` — current references, zones, levels per symbol
* `backtest`     — verification run by the shared backtest engine
* `provenance`   — data sources, config hash, generation timestamp

The same function backs the APEX paid endpoint (chain.py), the CLI
(`binacci spec`), and the CMC Skills Marketplace submission.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from .backtest import run_backtest
from .config import StrategyConfig, Timeframe
from .data import CandleSource, SyntheticSource
from .indicators import to_dataframe
from .models import Side
from .simulations import ReferenceBook, Sim02ReferenceUpdate, SimAEntryZone, SimBEntryLevel

SKILL_NAME = "binacci-reaction-strategy"
SKILL_VERSION = "0.1.0"


def _config_fingerprint(cfg: StrategyConfig) -> str:
    blob = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def strategy_rules(cfg: StrategyConfig) -> dict:
    """The deterministic rule set — the heart of the backtestable spec."""
    return {
        "philosophy": "Catch market reactions, not movements. References -> confirmations -> filters. Short guaranteed targets.",
        "entry_chain": [
            {"step": 1, "gate": "fresh_reference",
             "rule": "A current reference point (local max/min, fib structure, divergence pivot) must exist for the symbol/timeframe."},
            {"step": 2, "gate": "entry_zone",
             "rule": "Price in an entry zone: fib retracement of last impulse, recent hidden divergence, or Bollinger extreme."},
            {"step": 3, "gate": "filters_ok",
             "rule": "CMD momentum turning in trade direction, RSI not at the chased extreme, volume >= min ratio, BB position sane."},
            {"step": 4, "gate": "macro_ok",
             "rule": f"totalCap change >= {cfg.macro.total_cap_min_change_pct}%, BTC.D change <= {cfg.macro.btc_dominance_max_change_pct}%, USDT.D change <= {cfg.macro.usdt_dominance_max_change_pct}% over {cfg.macro.lookback_hours}h."},
            {"step": 5, "gate": "level_touch",
             "rule": "Limit entry AT a concrete level (log S/R, fib pivot, fib retracement, trend channel). Never market."},
        ],
        "execution": {
            "margin_model": {
                "reserve_pct": cfg.margin.reserve_pct,
                "working_pct": cfg.margin.working_pct,
                "entry_pct_of_deposit": cfg.margin.entry_pct_of_deposit,
                "averaging_multipliers": list(cfg.margin.averaging_multipliers),
                "position_cap_pct_of_deposit": cfg.margin.position_cap_pct(),
                "averaging_rule": "Only at a level, only while position is in drawdown. x4 then x2.",
            },
            "risk_limits": {
                "max_positions": cfg.risk.max_positions,
                "aggregate_drawdown_kill_pct": cfg.risk.max_aggregate_drawdown_pct,
                "smart_slot_return": cfg.risk.sl_in_profit_releases_slot,
            },
            "trailing_stop": {
                "trigger_pct": cfg.trailing.trigger_pct,
                "initial_sl_pct": cfg.trailing.initial_sl_pct,
                "step_pct": cfg.trailing.step_pct,
                "behavior": "SL steps into profit behind price; position almost cannot close red.",
            },
            "targets_pct_by_timeframe": {tf.value: cfg.target_for(tf) for tf in cfg.entry_timeframes},
            "order_type": cfg.entry_order_type,
        },
    }


def market_state(
    cfg: StrategyConfig, source: CandleSource, symbol: str, tf: Timeframe, bars: int = 400
) -> dict:
    """Current references / zone / candidate levels for one symbol."""
    candles = source.history(symbol, tf, bars)
    df = to_dataframe(candles)
    book = ReferenceBook()
    Sim02ReferenceUpdate(cfg.sims).step(symbol, tf, df, book)
    ref = book.get(symbol, tf)
    zone = SimAEntryZone(cfg.sims, cfg.filters).assess(df, Side.LONG)
    level = SimBEntryLevel(cfg.sims).pick(df, Side.LONG)
    price = float(df["close"].iloc[-1])
    return {
        "symbol": symbol,
        "timeframe": tf.value,
        "price": price,
        "reference": {
            "kind": ref.kind.value, "price": ref.price, "ts": ref.ts.isoformat(),
        } if ref else None,
        "zone": {"in_zone": zone.in_zone, "evidence": zone.reasons,
                 "filters_ok": zone.filters_ok, "filters": zone.filter_detail},
        "entry_level": {"price": level.price, "kind": level.kind,
                        "strength": level.strength} if level else None,
        "target_pct": cfg.target_for(tf),
    }


def generate_strategy_spec(
    cfg: StrategyConfig,
    symbol: str = "BNB",
    tf: Timeframe = Timeframe.H4,
    source: Optional[CandleSource] = None,
    backtest_bars: int = 1500,
    deposit_usd: float = 1000.0,
) -> dict:
    """The full Track 2 deliverable: rules + market state + verification
    backtest + provenance."""
    src = source or SyntheticSource()
    bt = run_backtest(cfg, src, symbol, tf, bars=backtest_bars, deposit_usd=deposit_usd)
    return {
        "skill": SKILL_NAME,
        "version": SKILL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy_rules(cfg),
        "market_state": market_state(cfg, src, symbol, tf),
        "backtest": bt.summary(),
        "provenance": {
            "data_source": type(src).__name__,
            "config_fingerprint": _config_fingerprint(cfg),
            "engine": "binacci.backtest (same engine as live agent)",
            "note": "Replayable: identical config + data window reproduces this backtest bit-for-bit.",
        },
    }


def skill_manifest() -> dict:
    """CMC Skills Marketplace manifest (submission metadata)."""
    return {
        "name": SKILL_NAME,
        "version": SKILL_VERSION,
        "description": (
            "Generates backtestable reaction-trading strategy specs from CMC market data. "
            "Five-simulation analysis (references, zones, levels), hard deterministic risk "
            "model (30/70 margin, x4/x2 averaging, 5-slot cap, 30% kill switch, stepped "
            "trailing SL). Output: machine-readable spec + verification backtest."
        ),
        "inputs": {
            "symbol": {"type": "string", "example": "BNB"},
            "timeframe": {"type": "string", "enum": [tf.value for tf in Timeframe], "example": "4h"},
        },
        "outputs": {
            "spec": "JSON strategy spec with entry chain, execution params, market state, backtest report",
        },
        "data_dependencies": [
            "CMC quotes (v2/cryptocurrency/quotes/latest)",
            "CMC OHLCV (v2/cryptocurrency/ohlcv/historical)",
            "CMC global metrics (v1/global-metrics/quotes/latest) — totalCap, BTC.D, USDT.D",
            "CMC technicals via MCP (RSI, Fibonacci, support/resistance) — cross-check",
        ],
        "monetization": "x402 pay-per-call and/or APEX (ERC-8183) escrowed jobs on BSC",
        "author": "Binacci / Brandon",
        "contact": "brandononchain@gmail.com",
    }
