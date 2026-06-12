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


class StrategyConfig(BaseSettings):
    """Top-level strategy configuration (env prefix ``BINACCI_``)."""

    model_config = SettingsConfigDict(env_prefix="BINACCI_", env_nested_delimiter="__")

    symbols: list[str] = Field(default_factory=lambda: ["BNB", "BTC", "ETH", "CAKE", "SOL"])
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

    #: Entries are ALWAYS limit orders at a level — never market.
    entry_order_type: str = "limit"
    #: Long-only by default (spot venue); perps venue may enable shorts.
    allow_shorts: bool = False

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StrategyConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(**data)

    @classmethod
    def load(cls) -> "StrategyConfig":
        """Production loader: if ``BINACCI_STRATEGY_FILE`` points at a private
        overlay YAML, merge it over the illustrative defaults. The private
        overlay (and the proprietary CMD implementation) live outside the
        public repo."""
        import os

        path = os.environ.get("BINACCI_STRATEGY_FILE", "")
        if path and Path(path).exists():
            return cls.from_yaml(path)
        return cls()

    def target_for(self, tf: Timeframe) -> float:
        return self.targets_pct.get(tf, DEFAULT_TARGETS[tf])


class RuntimeConfig(BaseSettings):
    """Operational settings: keys, endpoints, venue selection."""

    model_config = SettingsConfigDict(env_prefix="BINACCI_", env_file=".env", extra="ignore")

    cmc_api_key: str = ""
    cmc_base_url: str = "https://pro-api.coinmarketcap.com"
    cmc_mcp_url: str = "https://mcp.coinmarketcap.com/mcp"

    venue: str = "paper"  # paper | pancake | perps
    deposit_usd: float = 1000.0

    # Trust Wallet Agent Kit / chain
    twak_endpoint: str = ""
    bsc_rpc: str = "https://bsc-dataseed.bnbchain.org"
    bsc_testnet_rpc: str = "https://data-seed-prebsc-1-s1.bnbchain.org:8545"
    wallet_address: str = ""
    use_testnet: bool = True

    # Agent API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
