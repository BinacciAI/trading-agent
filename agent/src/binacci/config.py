"""Strategy configuration — every strategy parameter in one place.

Public defaults are ILLUSTRATIVE. Production values ship as a private
overlay (see the private `strategy-core` repo) loaded via the
``BINACCI_STRATEGY_FILE`` environment variable.
Nothing in the agent is allowed to change these at runtime; the AI layer is
an executor only. Override via environment variables (prefix ``BINACCI_``) or a
YAML file loaded with :func:`StrategyConfig.from_yaml`.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Timeframe(str, Enum):
    """The 12 entry timeframes. Analysis may run on more."""

    M3 = "3m"
    M10 = "10m"
    M13 = "13m"
    M15 = "15m"
    M21 = "21m"
    M30 = "30m"
    M45 = "45m"
    M89 = "89m"
    H4 = "4h"
    D1 = "1d"
    D3 = "3d"
    W1 = "1w"

    @property
    def minutes(self) -> int:
        return _TF_MINUTES[self]


_TF_MINUTES: dict[Timeframe, int] = {
    Timeframe.M3: 3,
    Timeframe.M10: 10,
    Timeframe.M13: 13,
    Timeframe.M15: 15,
    Timeframe.M21: 21,
    Timeframe.M30: 30,
    Timeframe.M45: 45,
    Timeframe.M89: 89,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
    Timeframe.D3: 4320,
    Timeframe.W1: 10080,
}

#: Take-profit target (% of entry price) per entry timeframe.
#: Doc: 0.3% minimum on the shortest TFs, ~1-2% typical, 5% max on 1d-1w.
DEFAULT_TARGETS: dict[Timeframe, float] = {
    Timeframe.M3: 0.30,
    Timeframe.M10: 0.40,
    Timeframe.M13: 0.45,
    Timeframe.M15: 0.50,
    Timeframe.M21: 0.60,
    Timeframe.M30: 0.75,
    Timeframe.M45: 1.00,
    Timeframe.M89: 1.50,
    Timeframe.H4: 2.00,
    Timeframe.D1: 3.00,
    Timeframe.D3: 4.00,
    Timeframe.W1: 5.00,
}


class MarginModel(BaseModel):
    """30/70 deposit split and per-entry sizing.

    * 30% of the deposit is reserved and never participates in sizing.
    * Each entry is 0.5% of the *working* margin = 0.35% of the deposit.
    * 1st averaging: x4 -> position becomes 1.75% of deposit (+1.40% add).
    * 2nd averaging: x2 -> position becomes ~3% of deposit (doubles).
    * One fully-averaged position therefore caps at ~3% of deposit.
    """

    reserve_pct: float = 0.30
    entry_pct_of_working: float = 0.005
    averaging_multipliers: tuple[float, ...] = (4.0, 2.0)

    @property
    def working_pct(self) -> float:
        return 1.0 - self.reserve_pct

    @property
    def entry_pct_of_deposit(self) -> float:
        return self.entry_pct_of_working * self.working_pct  # 0.0035

    def position_cap_pct(self) -> float:
        """Max share of deposit a fully averaged position can occupy."""
        size = self.entry_pct_of_deposit
        for m in self.averaging_multipliers:
            size *= m
        return size  # 0.0035 * 4 * 2 = 0.028 (~3%)


class TrailingModel(BaseModel):
    """Stepped trailing stop-loss into profit.

    Doc example: trigger fires at +0.4% -> SL instantly at +0.2%, then steps
    +0.1% for each further +0.1% the position gains (gap ~0.2%). Values are
    configurable; doc marks them illustrative.
    """

    trigger_pct: float = 0.40
    initial_sl_pct: float = 0.20
    step_pct: float = 0.10

    def stop_for(self, peak_gain_pct: float) -> Optional[float]:
        """SL level (in % gain from entry) for a given peak gain. None if
        the trigger has not fired yet."""
        if peak_gain_pct < self.trigger_pct:
            return None
        steps = int(round((peak_gain_pct - self.trigger_pct) / self.step_pct))
        return self.initial_sl_pct + steps * self.step_pct


class RiskLimits(BaseModel):
    """Hard, client-level circuit breakers."""

    max_positions: int = 5
    #: Aggregate floating drawdown across ALL open positions, as a share of
    #: deposit, at which everything is force-closed. The hard stop-cock.
    max_aggregate_drawdown_pct: float = 0.30
    #: Smart slot return: positions whose SL is already in profit are counted
    #: as "effectively closed" and release their slot.
    sl_in_profit_releases_slot: bool = True
    #: Per-position catastrophic stop: max adverse excursion (% from avg
    #: entry) before a single position is force-closed, EVEN if it never
    #: turned green. Without this, a position that goes straight against the
    #: entry has no stop until the aggregate kill switch — so a few averaged
    #: losers can erase many small wins (high win-rate, negative expectancy).
    #: Capping the tail loser is what makes the book net-positive. 0 disables.
    hard_stop_pct: float = 2.0


class RiskMode(str, Enum):
    """Named risk presets. They scale the NUMBER of concurrent positions and
    the per-entry size *together*, so a wider book stays just as conservative:
    more markets held at once, each a proportionally smaller slice, the same
    30% aggregate-drawdown kill switch and 30% reserve underneath. 'More
    positions' is diversification, not more risk."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    #: Use whatever RiskLimits/MarginModel already say (no preset applied).
    CUSTOM = "custom"


#: mode -> (max_positions, entry_pct_of_working). entry shrinks as slots grow
#: so the MAX fully-averaged deployed capital stays within the 70% working
#: margin: positions * (entry_pct_of_working * 0.7 * 8) <= ~0.70.
#: ``perps_leverage`` is the on-chain perp leverage applied to PERP-routed
#: positions in that mode (spot is always 1x). Higher leverage controls the
#: same notional with less posted margin — but it scales perp P/L AND drawdown
#: by the same factor, so the kill switch / liquidation sit proportionally
#: closer. Tiers: conservative 10x, balanced 25x, aggressive 50x.
RISK_PRESETS: dict[RiskMode, dict] = {
    RiskMode.CONSERVATIVE: {"max_positions": 15, "entry_pct_of_working": 0.0050, "perps_leverage": 10.0},
    RiskMode.BALANCED:     {"max_positions": 30, "entry_pct_of_working": 0.0035, "perps_leverage": 25.0},
    RiskMode.AGGRESSIVE:   {"max_positions": 50, "entry_pct_of_working": 0.0025, "perps_leverage": 50.0},
}


#: Regime-weighted allocation. The macro regime (from CMC global metrics + F&G)
#: tilts capital toward the strategies that fit it by scaling per-entry size in
#: [0,1] (1.0 = full, <1 = trimmed). Weights never exceed 1.0, so the risk
#: envelope is only ever reduced — never amplified. risk_off naturally cuts the
#: long-only spot strategies while keeping the both-ways perp fades working.
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "risk_on":  {"reaction": 1.0, "momentum_breakout": 1.0, "trend_follow": 1.0,
                 "mean_reversion": 0.5, "volatility_squeeze": 0.9,
                 "vwap_reversion": 0.5, "liquidity_sweep": 0.7, "funding_carry": 0.8, "basis_carry": 1.0},
    "chop":     {"reaction": 0.9, "momentum_breakout": 0.5, "trend_follow": 0.5,
                 "mean_reversion": 1.0, "volatility_squeeze": 0.9,
                 "vwap_reversion": 1.0, "liquidity_sweep": 1.0, "funding_carry": 1.0, "basis_carry": 1.0},
    "risk_off": {"reaction": 0.6, "momentum_breakout": 0.3, "trend_follow": 0.3,
                 "mean_reversion": 0.8, "volatility_squeeze": 0.7,
                 "vwap_reversion": 0.8, "liquidity_sweep": 0.9, "funding_carry": 1.0, "basis_carry": 1.0},
}


class FundingConfig(BaseModel):
    """Funding/basis carry: minimum |perp premium vs spot| (percent) to fade."""
    min_abs_funding_pct: float = 0.05


class FilterConfig(BaseModel):
    """Entry filters (SimA confirmation set + macro gate)."""

    rsi_period: int = 14
    rsi_oversold: float = 32.0
    rsi_overbought: float = 68.0
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    volume_lookback: int = 20
    #: Entry volume must exceed this multiple of average volume.
    volume_min_ratio: float = 1.15
    #: CMD is Binacci's proprietary composite momentum/direction filter.
    #: Implemented as EMA-spread momentum confirmation; pluggable.
    cmd_fast: int = 9
    cmd_slow: int = 26
    ichimoku_conversion: int = 9
    ichimoku_base: int = 26
    ichimoku_span_b: int = 52


class MacroConfig(BaseModel):
    """Macro gate: totalCap + BTC dominance + USDT dominance must agree."""

    enabled: bool = True
    #: For longs: total market cap change over the lookback must be above
    #: this floor (percent). Mild negative tolerated.
    total_cap_min_change_pct: float = -1.0
    #: For longs (alts): BTC dominance rising faster than this ceiling
    #: (percent change) blocks entry.
    btc_dominance_max_change_pct: float = 0.75
    #: USDT dominance rising = risk-off. Block longs above this change.
    usdt_dominance_max_change_pct: float = 0.50
    lookback_hours: int = 24


class SimulationConfig(BaseModel):
    """Parameters for the 5 simulations."""

    #: Sim01 cold start: replay this many days of history on boot.
    cold_start_days: int = 365
    #: Local extrema detection window (bars each side) for reference points.
    extrema_window: int = 12
    #: Fibonacci retracement levels used for reference / zone detection.
    fib_levels: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786)
    #: Zone tolerance: price within this % of a level counts as a touch.
    level_tolerance_pct: float = 0.15
    #: Divergence scan lookback (bars).
    divergence_lookback: int = 60
    #: Minimum bars between the two pivots of a divergence.
    divergence_min_gap: int = 5


# --------------------------------------------------------------------------
# Multi-strategy configuration
# --------------------------------------------------------------------------
# Binacci runs a *portfolio of strategies* concurrently. Each one is an
# independent opinion that still feeds the SAME deterministic execution
# engine (margin model, slot cap, trailing SL, kill switch). More strategies
# = more independent reasons to be in a market = wider trade opportunity,
# without loosening any risk rule. Toggle any of them on/off via env, e.g.
# ``BINACCI_STRATEGIES__MOMENTUM_BREAKOUT=false``.

class StrategyToggles(BaseModel):
    """Which strategies are active. All limit-entry, all risk-managed."""

    reaction: bool = True            # the core 5-gate reaction strategy
    momentum_breakout: bool = True   # Donchian breakout + retest
    mean_reversion: bool = True      # RSI/Bollinger oversold reclaim
    trend_follow: bool = True        # EMA-stack pullback
    volatility_squeeze: bool = True  # Bollinger squeeze release
    vwap_reversion: bool = True      # fade stretch from rolling VWAP
    liquidity_sweep: bool = True     # stop-run wick + reclaim
    funding_carry: bool = True       # perps funding/basis carry (fade the crowd)
    basis_carry: bool = True         # delta-neutral spot-perp basis carry


class BreakoutConfig(BaseModel):
    """Momentum breakout: enter the retest of a Donchian breakout."""

    donchian_period: int = 20
    volume_min_ratio: float = 1.20
    #: Retest limit sits this % below the broken level (buy the pullback).
    retest_band_pct: float = 0.35
    #: Target multiplier applied to the timeframe's base target.
    target_mult: float = 1.5
    require_macro: bool = True


class MeanReversionConfig(BaseModel):
    """Fade an oversold flush back to the mean."""

    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    bb_period: int = 20
    bb_std: float = 2.0
    #: Require the last bar to reclaim (close back inside the band).
    require_reclaim: bool = True
    target_mult: float = 1.0
    #: Counter-trend dip buys do not need a risk-on macro light.
    require_macro: bool = False


class TrendConfig(BaseModel):
    """Ride an established trend; enter on the pullback to the mid EMA."""

    ema_fast: int = 8
    ema_mid: int = 21
    ema_slow: int = 55
    #: Price must be within this % of the mid EMA to arm the pullback limit.
    pullback_tolerance_pct: float = 0.8
    target_mult: float = 1.25
    require_macro: bool = True


class SqueezeConfig(BaseModel):
    """Bollinger squeeze: low-bandwidth coil, then expansion breakout."""

    bb_period: int = 20
    bb_std: float = 2.0
    lookback: int = 120
    #: Bandwidth must sit in this lowest quantile to count as a squeeze.
    squeeze_quantile: float = 0.30
    #: Retest limit sits this % below the upper band on the breakout bar.
    retest_band_pct: float = 0.40
    target_mult: float = 1.5
    require_macro: bool = True


class StrategyConfig(BaseSettings):
    """Top-level strategy configuration (env prefix ``BINACCI_``)."""

    model_config = SettingsConfigDict(env_prefix="BINACCI_", env_nested_delimiter="__")

    #: Candidate universe — BSC-ecosystem tokens chosen for REAL PancakeSwap
    #: liquidity (BSC-native projects + the deepest Binance-Peg majors). The
    #: previous list was majority CEX-only majors (XRP, ADA, EOS, XLM...)
    #: that do not resolve as a BSC swap, so liquidity verification collapsed
    #: it to ~12. This list is weighted to BSC so 50+ survive verification.
    #: The live loop still TWAK-verifies each candidate and auto-drops any
    #: that are illiquid/unresolvable, so it remains an upper bound. CMC
    #: quotes use these tickers; swaps use :meth:`chain_symbol`.
    #: Override: BINACCI_SYMBOLS.
    symbols: list[str] = Field(default_factory=lambda: [
        # Track-1 competition-eligible BEP-20 tokens (CoinMarketCap list).
        # Trades OUTSIDE this list do not count toward the competition.
        # USDT is the quote currency (held/spent), so it's not a long target.
        "ETH", "USDC", "XRP", "TRX", "DOGE", "ZEC", "ADA", "LINK",
        "BCH", "DAI", "TON", "USD1", "USDe", "M", "LTC", "AVAX",
        "SHIB", "XAUt", "WLFI", "H", "DOT", "UNI", "ASTER", "DEXE",
        "USDD", "ETC", "AAVE", "ATOM", "U", "STABLE", "FIL", "INJ",
        "NIGHT", "FET", "TUSD", "BONK", "PENGU", "CAKE", "SIREN", "LUNC",
        "ZRO", "KITE", "FDUSD", "BEAT", "PIEVERSE", "BTT", "NFT", "EDGE",
        "FLOKI", "LDO", "B", "FF", "PENDLE", "NEX", "STG", "AXS",
        "TWT", "HOME", "RAY", "COMP", "GWEI", "XCN", "GENIUS", "XPL",
        "BAT", "SKYAI", "APE", "IP", "SFP", "TAG", "NXPC", "AB",
        "SAHARA", "1INCH", "CHEEMS", "BANANAS31", "RIVER", "MYX", "RAVE", "SNX",
        "FORM", "LAB", "HTX", "USDf", "CTM", "BDX", "SLX", "UB",
        "DUCKY", "FRAX", "BILL", "WFI", "KOGE", "ALE", "FRXUSD", "USDF",
        "GOMINING", "VCNT", "GUA", "DUSD", "SMILEK", "0G", "BEAM", "MY",
        "SOON", "REAL", "Q", "AIOZ", "ZIG", "YFI", "TAC", "lisUSD",
        "CYS", "ZAMA", "TRIA", "HUMA", "PLUME", "ZIL", "XPR", "ZETA",
        "BabyDoge", "NILA", "ROSE", "VELO", "UAI", "BRETT", "OPEN", "BSB",
        "TOSHI", "BAS", "ACH", "AXL", "LUR", "ELF", "KAVA", "APR",
        "IRYS", "EURI", "XUSD", "BARD", "DUSK", "SUSHI", "PEAQ", "COAI",
        "BDCA", "XAUM",
    ])
    #: CMC ticker -> on-chain BSC swap symbol, for the few that differ.
    #: (BTC trades as the Binance-Peg BTCB token on BSC, etc.) Identity for
    #: anything not listed here.
    chain_symbols: dict[str, str] = Field(default_factory=lambda: {
        "BTC": "BTCB",
    })
    quote: str = "USDT"
    entry_timeframes: list[Timeframe] = Field(
        default_factory=lambda: list(Timeframe)
    )
    targets_pct: dict[Timeframe, float] = Field(default_factory=lambda: dict(DEFAULT_TARGETS))

    margin: MarginModel = Field(default_factory=MarginModel)
    trailing: TrailingModel = Field(default_factory=TrailingModel)
    risk: RiskLimits = Field(default_factory=RiskLimits)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    macro: MacroConfig = Field(default_factory=MacroConfig)
    sims: SimulationConfig = Field(default_factory=SimulationConfig)

    #: Active strategies + their parameters (the multi-strategy portfolio).
    strategies: StrategyToggles = Field(default_factory=StrategyToggles)
    breakout: BreakoutConfig = Field(default_factory=BreakoutConfig)
    funding: FundingConfig = Field(default_factory=FundingConfig)
    mean_reversion: MeanReversionConfig = Field(default_factory=MeanReversionConfig)
    trend: TrendConfig = Field(default_factory=TrendConfig)
    squeeze: SqueezeConfig = Field(default_factory=SqueezeConfig)

    #: Entries are ALWAYS limit orders at a level — never market.
    entry_order_type: str = "limit"
    #: Long-only by default (spot venue); perps venue may enable shorts.
    allow_shorts: bool = False

    #: Binacci runs a SPOT book and a PERPS book at the same time. Each
    #: strategy is routed to one venue: spot strategies are long-only
    #: (PancakeSwap spot), perps strategies trade both ways with leverage.
    #: Both books share one risk engine + slot budget. A symbol can hold a
    #: spot position AND a perp position concurrently (different strategies).
    perp_strategies: set[str] = Field(default_factory=lambda: {
        "mean_reversion", "volatility_squeeze", "vwap_reversion", "liquidity_sweep",
        "funding_carry", "basis_carry",
    })
    #: Max share of the slot budget a single book (spot OR perps) may hold, so
    #: neither starves the other — guarantees perps stays live alongside spot.
    book_share: float = 0.7
    #: Perps leverage — P/L on perp positions scales by this. Spot is 1x.
    #: SET BY THE RISK MODE via :meth:`apply_risk_mode` (conservative 10x /
    #: balanced 25x / aggressive 50x). This 2.0 is only the bare-constructor
    #: default (so unit tests keep raw values); production goes through
    #: :meth:`load`, which applies the preset then honours an explicit
    #: BINACCI_PERPS_LEVERAGE override.
    perps_leverage: float = 2.0
    #: Perps take-profit multiplier — scales the timeframe base target for
    #: PERP-routed strategies only (spot is unaffected). Lifts perps above the
    #: ~0.3% short-TF floor so a winner can arm the trailing stop (trigger
    #: 0.40%) instead of insta-closing. 1.0 = legacy behaviour. Applied on top
    #: of any per-strategy target_mult. Override: BINACCI_PERPS_TARGET_MULT.
    perps_target_mult: float = 2.0
    #: Quality gate: minimum proposal strength (0..1) for a signal to park/fill.
    #: Higher = fewer, higher-conviction trades and a smoother equity curve.
    #: 0 keeps every setup. Override: BINACCI_MIN_STRENGTH.
    min_signal_strength: float = 0.0
    #: Regime-weighted allocation: tilt per-entry size by the macro regime.
    #: Disable with BINACCI_REGIME_WEIGHTING=false.
    regime_weighting: bool = True
    #: Fee-aware entry gate: refuse setups whose target can't clear the
    #: estimated round-trip on-chain fees + gas. Auto-on for live venues; off
    #: in paper (so the demo stays active). Override BINACCI_MIN_EDGE_GATE.
    min_edge_gate: bool = False

    #: Named risk preset. Applied by :meth:`load` (and the runtime switcher),
    #: NOT by the bare constructor — so unit tests keep the raw defaults.
    #: Override at boot: BINACCI_RISK_MODE=conservative|balanced|aggressive.
    risk_mode: RiskMode = RiskMode.BALANCED

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StrategyConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(**data)

    @classmethod
    def load(cls) -> "StrategyConfig":
        """Production loader: if ``BINACCI_STRATEGY_FILE`` points at a private
        overlay YAML, merge it over the illustrative defaults. The private
        overlay (and the proprietary CMD implementation) live outside the
        public repo. The configured risk preset is applied here (not in the
        bare constructor)."""
        import os

        path = os.environ.get("BINACCI_STRATEGY_FILE", "")
        cfg = cls.from_yaml(path) if (path and Path(path).exists()) else cls()
        cfg.apply_risk_mode(cfg.risk_mode)
        # Perps leverage source of truth. apply_risk_mode() has set
        # cfg.perps_leverage from the mode preset (10/25/50x). An explicit
        # BINACCI_PERPS_LEVERAGE always wins. We then write the resolved value
        # back to the env var because the venue/brain/api layers read leverage
        # straight from the environment — exporting it keeps every consumer on
        # the same number instead of silently falling back to the old 2x.
        env_lev = os.environ.get("BINACCI_PERPS_LEVERAGE")
        if env_lev is not None:
            try:
                cfg.perps_leverage = max(1.0, float(env_lev))
            except (TypeError, ValueError):
                pass
        try:
            cfg.perps_target_mult = max(1.0, float(os.environ.get("BINACCI_PERPS_TARGET_MULT", cfg.perps_target_mult)))
        except (TypeError, ValueError):
            pass
        try:
            cfg.min_signal_strength = max(0.0, min(1.0, float(os.environ.get("BINACCI_MIN_STRENGTH", cfg.min_signal_strength))))
        except (TypeError, ValueError):
            pass
        # Tighten exits live without a redeploy (locks profit sooner -> less
        # give-back, smoother curve). Defaults unchanged unless these are set.
        for _env, _attr in (("BINACCI_TRAIL_TRIGGER", "trigger_pct"),
                            ("BINACCI_TRAIL_INITIAL", "initial_sl_pct"),
                            ("BINACCI_TRAIL_STEP", "step_pct")):
            _v = os.environ.get(_env)
            if _v is not None:
                try:
                    setattr(cfg.trailing, _attr, max(0.0, float(_v)))
                except (TypeError, ValueError):
                    pass
        _rw = os.environ.get("BINACCI_REGIME_WEIGHTING")
        if _rw is not None:
            cfg.regime_weighting = _rw.strip().lower() in ("1", "true", "yes", "on")
        _meg = os.environ.get("BINACCI_MIN_EDGE_GATE")
        if _meg is not None:
            cfg.min_edge_gate = _meg.strip().lower() in ("1", "true", "yes", "on")
        cfg.apply_size_env()
        cfg.export_runtime_env()
        return cfg

    def export_runtime_env(self) -> None:
        """Push runtime-resolved values back into the environment so the
        env-reading consumers (perps venue leverage, brain/monitor displays)
        stay in lock-step with this cfg. MUST be called after any runtime
        change to ``perps_leverage`` (e.g. a live risk-mode switch) — otherwise
        the venue keeps signing at the old leverage while the engine stamps the
        new one, and the dashboard and chain disagree."""
        import os
        os.environ["BINACCI_PERPS_LEVERAGE"] = str(self.perps_leverage)
        os.environ["BINACCI_PERPS_TARGET_MULT"] = str(self.perps_target_mult)

    def apply_risk_mode(self, mode: RiskMode | str) -> "StrategyConfig":
        """Apply a named risk preset: scales slot count and per-entry size
        together so aggregate exposure stays bounded. ``custom`` is a no-op."""
        mode = RiskMode(mode)
        self.risk_mode = mode
        preset = RISK_PRESETS.get(mode)
        if preset:
            self.risk.max_positions = preset["max_positions"]
            self.margin.entry_pct_of_working = preset["entry_pct_of_working"]
            self.perps_leverage = preset["perps_leverage"]
        return self

    def risk_summary(self) -> dict:
        """Human-readable snapshot of the active risk envelope."""
        cap = self.margin.position_cap_pct()
        return {
            "risk_mode": self.risk_mode.value,
            "max_positions": self.risk.max_positions,
            "reserve_pct": self.margin.reserve_pct,
            "entry_pct_of_deposit": round(self.margin.entry_pct_of_deposit, 5),
            "position_cap_pct_of_deposit": round(cap, 5),
            "max_deployed_pct_of_deposit": round(cap * self.risk.max_positions, 4),
            "aggregate_drawdown_kill_pct": self.risk.max_aggregate_drawdown_pct,
            "perps_leverage": self.perps_leverage,
            "perps_target_mult": self.perps_target_mult,
        }

    def market_for(self, strategy: str) -> str:
        """Which venue a strategy trades on: 'perp' (both-ways, leverage) or
        'spot' (long-only). Both books run simultaneously. Deterministic —
        the single source of truth for a position's book."""
        return "perp" if strategy in self.perp_strategies else "spot"

    def book_cap(self) -> int:
        """Max open positions a single book may hold (reserves room for the
        other book so spot and perps are always live together)."""
        return max(1, int(self.risk.max_positions * self.book_share + 0.999))

    def apply_size_env(self) -> "StrategyConfig":
        """Structural overrides for fee-efficient sizing on small deposits:
        bigger/fewer positions so notional clears fixed gas. These override the
        risk-mode preset, so call them LAST (after apply_risk_mode / operator
        settings)."""
        import os
        try:
            self.margin.entry_pct_of_working = max(1e-5, float(
                os.environ.get("BINACCI_ENTRY_PCT_WORKING", self.margin.entry_pct_of_working)))
        except (TypeError, ValueError):
            pass
        try:
            self.risk.max_positions = max(1, int(float(
                os.environ.get("BINACCI_MAX_POSITIONS", self.risk.max_positions))))
        except (TypeError, ValueError):
            pass
        _avg = os.environ.get("BINACCI_AVERAGING")
        if _avg:
            try:
                self.margin.averaging_multipliers = tuple(
                    float(x) for x in _avg.split(",") if x.strip())
            except (TypeError, ValueError):
                pass
        return self

    def regime_size_mult(self, regime: str, strategy: str) -> float:
        """Per-entry size multiplier in [0,1] for a strategy in a regime.
        1.0 when weighting is off or the regime/strategy is unmapped."""
        if not self.regime_weighting:
            return 1.0
        return float(REGIME_WEIGHTS.get(regime, {}).get(strategy, 1.0))

    def target_for(self, tf: Timeframe) -> float:
        return self.targets_pct.get(tf, DEFAULT_TARGETS[tf])

    def chain_symbol(self, symbol: str) -> str:
        """The symbol to swap on-chain for a given CMC ticker."""
        return self.chain_symbols.get(symbol, symbol)


class RuntimeConfig(BaseSettings):
    """Operational settings: keys, endpoints, venue selection."""

    model_config = SettingsConfigDict(env_prefix="BINACCI_", env_file=".env", extra="ignore")

    cmc_api_key: str = ""
    cmc_base_url: str = "https://pro-api.coinmarketcap.com"
    cmc_mcp_url: str = "https://mcp.coinmarketcap.com/mcp"

    venue: str = "paper"  # paper | pancake | perps
    deposit_usd: float = 1000.0
    #: Live loop poll interval (seconds). One batched CMC quotes call per
    #: poll regardless of symbol count (1 credit covers up to 100 symbols).
    poll_seconds: int = 30
    #: Macro gate refresh interval (seconds). Global-metrics is 1 credit per
    #: refresh, so this is decoupled from poll_seconds to control credit burn.
    macro_refresh_seconds: int = 600
    #: Fear & Greed refresh interval (seconds) — cheap context, refreshed
    #: rarely. Set 0 to disable the F&G call entirely.
    fear_greed_refresh_seconds: int = 3600
    #: Only poll CMC quotes for liquidity-VERIFIED symbols once verification
    #: completes (live venues only). Stops paying for quotes on coins that can
    #: never trade — the single biggest source of wasted CMC credits. Paper
    #: mode always analyses the full universe.
    poll_only_verified: bool = True
    #: Best-effort: on boot, backfill historical OHLCV from CMC so references
    #: exist immediately instead of warming up over many hours from live
    #: ticks. Silently falls back to live accumulation if unavailable.
    warmup_backfill: bool = True
    warmup_backfill_bars: int = 320
    #: Liquidity verification: "auto" (verify when twak is installed),
    #: "true", or "false". Unverified symbols never reach the live venue.
    verify_liquidity: str = "auto"
    #: Drop candidates whose $1 test-quote price impact exceeds this (%).
    max_price_impact_pct: float = 1.0

    # Trust Wallet Agent Kit / chain
    twak_endpoint: str = ""
    bsc_rpc: str = "https://bsc-dataseed.bnbchain.org"
    bsc_testnet_rpc: str = "https://data-seed-prebsc-1-s1.bnbchain.org:8545"
    wallet_address: str = ""
    use_testnet: bool = True

    # ---- live-funds execution safety (real money path) ----
    #: Spot swap slippage tolerance (%). Close uses this x close_slippage_mult.
    spot_slippage_pct: float = 0.5
    close_slippage_mult: float = 1.6
    #: Route swaps through a private/MEV-protected relay when the installed
    #: twak build supports it (passes --private). Off by default — only enable
    #: if your CLI honours it, else swaps may error.
    mev_protect: bool = False
    #: After a venue returns a tx hash, verify the on-chain receipt status via
    #: JSON-RPC before trusting the fill. A reverted tx -> the fill is rejected
    #: and the engine rolls back. Unconfirmed (timeout) -> kept but flagged.
    confirm_receipts: bool = True
    receipt_timeout_s: int = 75
    receipt_poll_s: float = 3.0
    #: Transient venue failures are retried this many extra times before the
    #: engine rolls back (open) or reverts+halts (close).
    venue_max_retries: int = 2
    #: On boot, reconcile restored engine positions against the chain. If
    #: restored open positions can't be independently verified, new trading is
    #: HALTED until a human acks (/venue/reconcile/ack) — unless auto-ack.
    reconcile_auto_ack: bool = False
    #: Track-1 on-chain competition contract (records the agent wallet on the
    #: immutable participant list). Registration via `twak compete register`.
    competition_contract: str = "0x212c61b9b72c95d95bf29cf032f5e5635629aed5"

    # Agent API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
