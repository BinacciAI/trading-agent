"""Macro gate: totalCap + BTC dominance + USDT dominance.

Step 04 of the entry chain — the overall market must give a green light.
Live mode feeds this from CMC Global Metrics (Data API / MCP); backtests
feed it from recorded snapshots or disable it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import MacroConfig
from .models import Side


@dataclass(slots=True)
class MacroSnapshot:
    total_market_cap_usd: float
    btc_dominance_pct: float
    usdt_dominance_pct: float
    #: change over cfg.lookback_hours, in percent
    total_cap_change_pct: float
    btc_dominance_change_pct: float
    usdt_dominance_change_pct: float
    fear_greed: Optional[int] = None


@dataclass(slots=True)
class MacroVerdict:
    ok: bool
    detail: str


def evaluate_macro(snap: Optional[MacroSnapshot], cfg: MacroConfig, side: Side = Side.LONG) -> MacroVerdict:
    if not cfg.enabled:
        return MacroVerdict(True, "macro filter disabled")
    if snap is None:
        return MacroVerdict(False, "no macro data — fail closed")

    if side is Side.LONG:
        checks = [
            (snap.total_cap_change_pct >= cfg.total_cap_min_change_pct,
             f"totalCap {snap.total_cap_change_pct:+.2f}% >= {cfg.total_cap_min_change_pct}%"),
            (snap.btc_dominance_change_pct <= cfg.btc_dominance_max_change_pct,
             f"BTC.D {snap.btc_dominance_change_pct:+.2f}% <= {cfg.btc_dominance_max_change_pct}%"),
            (snap.usdt_dominance_change_pct <= cfg.usdt_dominance_max_change_pct,
             f"USDT.D {snap.usdt_dominance_change_pct:+.2f}% <= {cfg.usdt_dominance_max_change_pct}%"),
        ]
    else:  # shorts invert the risk-on logic
        checks = [
            (snap.total_cap_change_pct <= -cfg.total_cap_min_change_pct,
             f"totalCap {snap.total_cap_change_pct:+.2f}% <= {-cfg.total_cap_min_change_pct}%"),
            (snap.usdt_dominance_change_pct >= -cfg.usdt_dominance_max_change_pct,
             f"USDT.D {snap.usdt_dominance_change_pct:+.2f}% >= {-cfg.usdt_dominance_max_change_pct}%"),
        ]

    failed = [msg for ok, msg in checks if not ok]
    if failed:
        return MacroVerdict(False, "blocked: " + "; ".join(failed))
    return MacroVerdict(True, "; ".join(msg for _, msg in checks))
