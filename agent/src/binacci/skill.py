"""Track 2 — CMC Strategy Skills: backtestable strategy spec generation.

Binacci ships a *family* of strategy skills, one per strategy in the live
portfolio. Each skill takes CMC market data and emits a **backtestable spec**
— a machine-readable, replayable description of the strategy's rules,
execution parameters, current market state, and a verification backtest run
by the SAME engine the live agent uses. This is "quant research" output, not
a live agent (exactly what Track 2 asks for).

Every skill shares:
* `strategy`     — rules, parameters, gates (deterministic, replayable)
* `market_state` — current setup for the requested symbol/timeframe
* `backtest`     — verification run by :mod:`binacci.backtest`
* `provenance`   — data sources, config hash, generation timestamp
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
from .simulations import ReferenceBook, Sim02ReferenceUpdate
from .strategies import ALL_STRATEGY_NAMES, build_strategies, get_strategy

SKILL_FAMILY = "binacci"
SKILL_VERSION = "0.2.0"


STRATEGY_META: dict[str, dict] = {
    "reaction": {
        "title": "Reaction (5-gate)",
        "philosophy": "Catch market reactions, not movements. References -> confirmations -> filters -> macro -> level. Short guaranteed targets.",
        "entry_logic": "Patient, high-conviction. Fib/divergence/Bollinger zone, confirmed by CMD+RSI+volume, gated by macro, filled at a concrete log-S/R or fib level.",
        "gates": ["fresh_reference", "entry_zone", "filters_ok", "macro_ok", "level_touch"],
        "requires_macro": True,
    },
    "momentum_breakout": {
        "title": "Momentum Breakout",
        "philosophy": "Trend ignition leaves a footprint: a clean break of range with volume.",
        "entry_logic": "Close above the prior N-bar Donchian high with rising CMD and a volume expansion; limit parked at the breakout retest (never a market chase).",
        "gates": ["donchian_breakout", "cmd_rising", "volume_expansion", "macro_ok", "retest_touch"],
        "requires_macro": True,
    },
    "mean_reversion": {
        "title": "Mean Reversion (oversold reclaim)",
        "philosophy": "Capitulation overshoots; the snap back to the mean is tradable.",
        "entry_logic": "RSI deeply oversold AND price pierced the lower Bollinger band, then reclaimed it; limit parked at the band. Explicitly counter-trend — no macro light required.",
        "gates": ["rsi_oversold", "bb_lower_pierce", "reclaim", "level_touch"],
        "requires_macro": False,
    },
    "trend_follow": {
        "title": "Trend Follow (EMA-stack pullback)",
        "philosophy": "The trend is the edge; buy the pullback, not the breakout.",
        "entry_logic": "Fast/mid/slow EMAs stacked bullishly with a non-declining slow EMA; limit parked at the mid EMA pullback. Trailing SL lets it run.",
        "gates": ["ema_stack_aligned", "pullback_to_mid", "macro_ok", "level_touch"],
        "requires_macro": True,
    },
    "volatility_squeeze": {
        "title": "Volatility Squeeze",
        "philosophy": "Low volatility is potential energy; expansion releases it.",
        "entry_logic": "Bollinger bandwidth in a low-percentile coil, then a close above the upper band; limit parked at the breakout retest.",
        "gates": ["bandwidth_squeeze", "upper_band_break", "macro_ok", "retest_touch"],
        "requires_macro": True,
    },
    "vwap_reversion": {
        "title": "VWAP Reversion",
        "philosophy": "Price rubber-bands back to where volume actually traded.",
        "entry_logic": "Price stretched well below rolling VWAP and turning back up (RSI not chased); limit parked to buy the snap to the mean. Counter-trend — no macro light required.",
        "gates": ["below_vwap_stretch", "turning_up", "rsi_ok", "level_touch"],
        "requires_macro": False,
    },
    "liquidity_sweep": {
        "title": "Liquidity Sweep Reclaim",
        "philosophy": "Stop-runs trap late sellers; the reclaim is the reversal.",
        "entry_logic": "Price wicks below a recent swing low (sweeping resting liquidity) then closes back above it; limit parked at the reclaimed level. Counter-trend.",
        "gates": ["swing_low_swept", "reclaim", "level_touch"],
        "requires_macro": False,
    },
    "funding_carry": {
        "title": "Perps Funding / Basis Carry",
        "philosophy": "Crowded leverage pays for the privilege; fade the side that is paying.",
        "entry_logic": "Derive funding from the on-chain perp mark vs CMC spot. Sustained premium (crowded longs) -> fade short; discount (crowded shorts) -> fade long. Perps-only, both ways.",
        "gates": ["funding_extreme", "level_touch"],
        "requires_macro": False,
    },
}


def skill_name(strategy: str) -> str:
    return f"{SKILL_FAMILY}-{strategy.replace('_', '-')}-strategy"


def strategy_catalog() -> list[dict]:
    """Lightweight catalog of every strategy (for /strategies + docs)."""
    return [{"strategy": n, "skill": skill_name(n), **{k: v for k, v in STRATEGY_META[n].items()}}
            for n in ALL_STRATEGY_NAMES]


def _config_fingerprint(cfg: StrategyConfig) -> str:
    blob = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _config_for(strategy: str, cfg: StrategyConfig) -> StrategyConfig:
    """A config copy with ONLY the requested strategy enabled."""
    c = cfg.model_copy(deep=True)
    for name in ALL_STRATEGY_NAMES:
        setattr(c.strategies, name, name == strategy)
    return c


def _execution_block(cfg: StrategyConfig) -> dict:
    return {
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
            "position_key": "(symbol, timeframe, strategy)",
        },
        "trailing_stop": {
            "trigger_pct": cfg.trailing.trigger_pct,
            "initial_sl_pct": cfg.trailing.initial_sl_pct,
            "step_pct": cfg.trailing.step_pct,
            "behavior": "SL steps into profit behind price; position almost cannot close red.",
        },
        "targets_pct_by_timeframe": {tf.value: cfg.target_for(tf) for tf in cfg.entry_timeframes},
        "order_type": cfg.entry_order_type,
    }


def _strategy_params(strategy: str, cfg: StrategyConfig) -> dict:
    if strategy == "reaction":
        return {
            "filters": cfg.filters.model_dump(),
            "fib_levels": list(cfg.sims.fib_levels),
            "extrema_window": cfg.sims.extrema_window,
            "level_tolerance_pct": cfg.sims.level_tolerance_pct,
        }
    return {
        "momentum_breakout": lambda: cfg.breakout.model_dump(),
        "mean_reversion": lambda: cfg.mean_reversion.model_dump(),
        "trend_follow": lambda: cfg.trend.model_dump(),
        "volatility_squeeze": lambda: cfg.squeeze.model_dump(),
        "vwap_reversion": lambda: {"window": 30, "stretch_pct": 0.8,
                                    "rsi_period": cfg.filters.rsi_period},
        "liquidity_sweep": lambda: {"lookback_bars": cfg.sims.extrema_window * 2 + 4},
    }.get(strategy, lambda: {})()


def strategy_rules(cfg: StrategyConfig, strategy: str = "reaction") -> dict:
    if strategy == "reaction":
        return {
            "strategy": "reaction",
            "philosophy": STRATEGY_META["reaction"]["philosophy"],
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
            "parameters": _strategy_params("reaction", cfg),
            "execution": _execution_block(cfg),
        }
    meta = STRATEGY_META[strategy]
    return {
        "strategy": strategy,
        "philosophy": meta["philosophy"],
        "entry_logic": meta["entry_logic"],
        "entry_chain": [{"step": i + 1, "gate": g} for i, g in enumerate(meta["gates"])],
        "requires_macro": meta["requires_macro"],
        "parameters": _strategy_params(strategy, cfg),
        "execution": _execution_block(cfg),
    }


def market_state(cfg: StrategyConfig, source: CandleSource, symbol: str,
                 tf: Timeframe, strategy: str = "reaction", bars: int = 400) -> dict:
    candles = source.history(symbol, tf, bars)
    df = to_dataframe(candles)
    book = ReferenceBook()
    Sim02ReferenceUpdate(cfg.sims).step(symbol, tf, df, book)
    ref = book.get(symbol, tf)
    strat = get_strategy(cfg, strategy)
    proposal = strat.propose(symbol, tf, df, Side.LONG) if len(df) >= strat.min_bars else None
    price = float(df["close"].iloc[-1])
    return {
        "symbol": symbol,
        "timeframe": tf.value,
        "strategy": strategy,
        "price": price,
        "reference": {
            "kind": ref.kind.value, "price": ref.price, "ts": ref.ts.isoformat(),
        } if ref else None,
        "proposal": {
            "in_setup": proposal is not None,
            "level_price": proposal.level_price if proposal else None,
            "level_kind": proposal.level_kind if proposal else None,
            "reasons": proposal.reasons if proposal else [],
            "target_pct": (
                ((proposal.target_pct if proposal and proposal.target_pct is not None
                  else cfg.target_for(tf))
                 * (cfg.perps_target_mult if cfg.market_for(strategy) == "perp" else 1.0))
            ),
        },
    }


def generate_strategy_spec(
    cfg: StrategyConfig,
    symbol: str = "BNB",
    tf: Timeframe = Timeframe.H4,
    source: Optional[CandleSource] = None,
    backtest_bars: int = 1500,
    deposit_usd: float = 1000.0,
    strategy: str = "reaction",
) -> dict:
    if strategy not in ALL_STRATEGY_NAMES:
        raise KeyError(f"unknown strategy {strategy!r}; have {ALL_STRATEGY_NAMES}")
    src = source or SyntheticSource()
    iso_cfg = _config_for(strategy, cfg)
    bt = run_backtest(iso_cfg, src, symbol, tf, bars=backtest_bars, deposit_usd=deposit_usd)
    return {
        "skill": skill_name(strategy),
        "strategy_name": strategy,
        "family": SKILL_FAMILY,
        "version": SKILL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy_rules(cfg, strategy),
        "market_state": market_state(iso_cfg, src, symbol, tf, strategy),
        "backtest": bt.summary(),
        "provenance": {
            "data_source": type(src).__name__,
            "config_fingerprint": _config_fingerprint(iso_cfg),
            "engine": "binacci.backtest (same engine as live agent)",
            "note": "Replayable: identical config + data window reproduces this backtest bit-for-bit.",
        },
    }


def generate_portfolio_spec(
    cfg: StrategyConfig,
    symbol: str = "BNB",
    tf: Timeframe = Timeframe.H4,
    source: Optional[CandleSource] = None,
    backtest_bars: int = 1500,
    deposit_usd: float = 1000.0,
) -> dict:
    src = source or SyntheticSource()
    active = [s.name for s in build_strategies(cfg)]
    combined = run_backtest(cfg, src, symbol, tf, bars=backtest_bars, deposit_usd=deposit_usd)
    return {
        "skill": f"{SKILL_FAMILY}-portfolio",
        "version": SKILL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_strategies": active,
        "per_strategy": {
            name: generate_strategy_spec(cfg, symbol, tf, src, backtest_bars, deposit_usd, name)
            for name in active
        },
        "combined_backtest": combined.summary(),
        "provenance": {
            "data_source": type(src).__name__,
            "config_fingerprint": _config_fingerprint(cfg),
            "engine": "binacci.backtest (same engine as live agent)",
        },
    }


def skill_manifest(strategy: str = "reaction") -> dict:
    meta = STRATEGY_META[strategy]
    return {
        "name": skill_name(strategy),
        "version": SKILL_VERSION,
        "title": meta["title"],
        "description": (
            f"{meta['title']} — generates a backtestable trading-strategy spec from CMC "
            f"market data. {meta['entry_logic']} Output: machine-readable spec + verification "
            f"backtest, run by the same engine as the live Binacci agent. Shared hard risk "
            f"model (30/70 margin, x4/x2 averaging, 5-slot cap, 30% kill switch, stepped trailing SL)."
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


def all_skill_manifests() -> list[dict]:
    return [skill_manifest(n) for n in ALL_STRATEGY_NAMES]
