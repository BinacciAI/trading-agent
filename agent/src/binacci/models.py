"""Domain models shared across analysis, execution, and venues."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .config import Timeframe


@dataclass(slots=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class RefKind(str, Enum):
    """How a reference point was derived (Sim02/Sim03 inputs)."""

    LOCAL_MIN = "local_min"
    LOCAL_MAX = "local_max"
    FIB_RETRACEMENT = "fib_retracement"
    FIB_PIVOT = "fib_pivot"
    DIVERGENCE = "divergence"
    CANDLE_PATTERN = "candle_pattern"


@dataclass(slots=True)
class ReferencePoint:
    """An anchor the strategy trades reactions from.

    The market's maximum minima / maxima are critical anchors: the next
    entry is always searched relative to them.
    """

    symbol: str
    timeframe: Timeframe
    kind: RefKind
    price: float
    ts: datetime
    #: True if produced by Sim03 (clean, filter-free pipeline).
    clean: bool = False
    meta: dict = field(default_factory=dict)


class GateStep(str, Enum):
    """The 5-step entry chain. If any step fails — no entry."""

    REFERENCE = "fresh_reference"
    ZONE = "entry_zone"
    FILTERS = "filters_ok"
    MACRO = "macro_ok"
    LEVEL = "level_touch"


@dataclass(slots=True)
class GateResult:
    step: GateStep
    passed: bool
    detail: str = ""


@dataclass(slots=True)
class EntrySignal:
    """Fully-confirmed entry: every gate passed, level identified."""

    symbol: str
    timeframe: Timeframe
    side: Side
    level_price: float
    reference: ReferencePoint
    gates: list[GateResult]
    ts: datetime
    target_pct: float
    #: Which strategy produced this signal. Positions are unique per
    #: (symbol, timeframe, strategy), so independent strategies can hold
    #: concurrent positions on the same market.
    strategy: str = "reaction"
    meta: dict = field(default_factory=dict)


class PositionState(str, Enum):
    PENDING = "pending"          # limit order resting at level
    OPEN = "open"
    SL_IN_PROFIT = "sl_in_profit"  # trailing armed; slot released
    CLOSED = "closed"


@dataclass(slots=True)
class Fill:
    ts: datetime
    price: float
    qty: float
    notional_usd: float
    tag: str  # "entry" | "avg1" | "avg2" | "exit"


@dataclass
class Position:
    symbol: str
    timeframe: Timeframe
    side: Side
    state: PositionState = PositionState.PENDING
    fills: list[Fill] = field(default_factory=list)
    averaging_done: int = 0          # 0, 1, or 2
    peak_gain_pct: float = 0.0
    stop_pct: Optional[float] = None  # gain-% where trailing SL sits
    target_pct: float = 1.0
    opened_ts: Optional[datetime] = None
    closed_ts: Optional[datetime] = None
    close_reason: str = ""
    realized_pnl_usd: float = 0.0
    meta: dict = field(default_factory=dict)

    # ---- derived ----
    @property
    def qty(self) -> float:
        return sum(f.qty for f in self.fills if f.tag != "exit")

    @property
    def notional_usd(self) -> float:
        return sum(f.notional_usd for f in self.fills if f.tag != "exit")

    @property
    def avg_entry(self) -> float:
        q = self.qty
        return (self.notional_usd / q) if q else 0.0

    def gain_pct(self, price: float) -> float:
        e = self.avg_entry
        if not e:
            return 0.0
        raw = (price - e) / e * 100.0
        return raw if self.side is Side.LONG else -raw

    def unrealized_pnl_usd(self, price: float) -> float:
        return self.notional_usd * self.gain_pct(price) / 100.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
