"""Execution-quality agent — routes each order for minimum all-in cost.

Two levers over a naive market swap:
  1. POOL TIER. PancakeSwap V3 0.05% pools exist for liquid pairs; routing
     through them instead of V2's 0.25% cuts the swap fee 5x (spot round-trip
     0.50% -> 0.10%). Illiquid pairs fall back to V2.
  2. PRICE IMPACT + SLICING. Impact grows with order size / pool depth; large
     orders are split into N child fills so each stays under a max-impact cap
     (gas cost rises with slices, so the router balances impact vs gas).

It is the cost authority used by the engine (net-of-fee P/L), the fee-aware
entry gate (breakeven), and the live spot venue (tier + slippage). Rates are
env-tunable; defaults are conservative BSC values.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from .fees import fee_model


def _f(env: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(env, default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Route:
    tier: str
    fee_bps: float       # per side
    impact_bps: float    # per side, after slicing
    slices: int
    gas_usd: float       # per on-chain action


class ExecutionRouter:
    def __init__(self) -> None:
        fm = fee_model()
        self.v3_fee_bps = _f("BINACCI_V3_FEE_BPS", 5.0)      # 0.05%
        self.v2_fee_bps = fm.swap_fee_bps                     # 0.25%
        self.perp_fee_bps = fm.perp_fee_bps                   # 0.08%/side
        self.funding_bps_hr = fm.perp_funding_bps_per_hr
        self.gas_usd = fm.gas_usd
        #: assumed routable pool depth ($) for the constant-product impact model
        self.pool_depth_usd = _f("BINACCI_POOL_DEPTH_USD", 1_500_000.0)
        #: split an order so each child stays under this price impact
        self.max_impact_bps = _f("BINACCI_MAX_IMPACT_BPS", 15.0)
        #: symbols WITHOUT a deep V3 0.05% pool -> fall back to V2 0.25%
        self.v2_only = set(x.strip().upper() for x in
                           os.environ.get("BINACCI_V2_ONLY_SYMBOLS", "").split(",") if x.strip())

    def _impact_slices(self, usd: float) -> tuple[float, int]:
        raw = usd / max(self.pool_depth_usd, 1.0) * 1e4   # bps
        slices = max(1, math.ceil(raw / self.max_impact_bps)) if raw > self.max_impact_bps else 1
        return raw / slices, slices   # splitting cuts per-child impact ~linearly

    def spot_route(self, symbol: str, usd: float) -> Route:
        use_v3 = (symbol or "").upper() not in self.v2_only
        fee = self.v3_fee_bps if use_v3 else self.v2_fee_bps
        impact, slices = self._impact_slices(usd)
        return Route("v3_0.05%" if use_v3 else "v2_0.25%", fee, impact, slices, self.gas_usd)

    def perp_route(self, symbol: str, notional: float) -> Route:
        impact, _ = self._impact_slices(notional)
        return Route("perp", self.perp_fee_bps, impact, 1, self.gas_usd)

    # ---- cost authority (used by engine + gate) ----
    def roundtrip_cost_usd(self, market: str, margin_usd: float, leverage: float = 1.0,
                           hours_held: float = 0.0, symbol: str = "") -> float:
        if market == "perp":
            notl = margin_usd * leverage
            r = self.perp_route(symbol, notl)
            fee = notl * ((r.fee_bps + r.impact_bps) / 1e4) * 2
            funding = notl * (self.funding_bps_hr / 1e4) * max(0.0, hours_held)
            return fee + funding + r.gas_usd * 2
        r = self.spot_route(symbol, margin_usd)
        return margin_usd * ((r.fee_bps + r.impact_bps) / 1e4) * 2 + r.gas_usd * 2 * r.slices

    def breakeven_move_pct(self, market: str, notional_usd: float, symbol: str = "") -> float:
        r = self.perp_route(symbol, notional_usd) if market == "perp" else self.spot_route(symbol, notional_usd)
        gas = r.gas_usd * 2 * (1 if market == "perp" else r.slices)
        return (r.fee_bps + r.impact_bps) * 2 / 1e4 * 100 + gas / max(notional_usd, 1e-9) * 100

    def summary(self, deposit_usd: float = 1000.0, entry_pct_of_deposit: float = 0.0035,
                leverage: float = 25.0) -> dict:
        margin = deposit_usd * entry_pct_of_deposit
        sr = self.spot_route("BNB", margin)
        pr = self.perp_route("BNB", margin * leverage)
        return {
            "spot_tier": sr.tier, "spot_fee_pct_per_swap": round(sr.fee_bps / 100, 4),
            "perp_fee_pct_per_side": round(pr.fee_bps / 100, 4),
            "max_impact_pct": round(self.max_impact_bps / 100, 3),
            "pool_depth_usd": self.pool_depth_usd,
            "example_breakeven_pct": {
                "spot": round(self.breakeven_move_pct("spot", margin, "BNB"), 3),
                "perp": round(self.breakeven_move_pct("perp", margin * leverage, "BNB"), 3),
            },
        }


_ROUTER: ExecutionRouter | None = None


def execution_router() -> ExecutionRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ExecutionRouter()
    return _ROUTER
