"""On-chain trading-cost model — PancakeSwap spot swaps + on-chain perps (BSC).

Every rate is env-overridable because it depends on the exact pool / perp
venue. Defaults are conservative BSC values. The model answers two questions:

  1. What does a round trip COST (so realized P/L can be booked net-of-fees)?
  2. What price move does a trade need just to BREAK EVEN on fees (so the
     engine can refuse setups whose target can't clear costs)?

Key identity: for both spot and perps the trading fee is a % of *notional*,
and gross P/L is move% * notional — so the breakeven *price move* equals the
round-trip fee rate and is INDEPENDENT of leverage. Leverage scales P/L and
fees by the same factor; it does not change whether a move is profitable.
Gas is a fixed $ cost, so it matters more on smaller notionals.
"""

from __future__ import annotations

import os


def _f(env: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(env, default)))
    except (TypeError, ValueError):
        return default


class FeeModel:
    def __init__(self) -> None:
        # PancakeSwap LP fee per swap. V2 = 0.25%; V3 pools 0.01/0.05/0.25/1%.
        self.swap_fee_bps = _f("BINACCI_SWAP_FEE_BPS", 25.0)        # 0.25% / swap
        # On-chain perp open/close fee per side, on notional (BSC perp DEXs ~0.04–0.10%).
        self.perp_fee_bps = _f("BINACCI_PERP_FEE_BPS", 8.0)         # 0.08% / side
        # Funding per hour on notional (avg magnitude; sign depends on side/imbalance).
        self.perp_funding_bps_per_hr = _f("BINACCI_PERP_FUNDING_BPS_HR", 1.0)  # 0.01% / hr
        # Gas per on-chain action (USD): BSC swap ~150k gas @ ~1 gwei, BNB ≈ $600.
        self.gas_usd = _f("BINACCI_GAS_USD", 0.12)

    # ---- cost of a round trip (entry + exit), in USD ----
    def spot_roundtrip_usd(self, notional_usd: float) -> float:
        return notional_usd * (self.swap_fee_bps / 1e4) * 2 + self.gas_usd * 2

    def perp_roundtrip_usd(self, notional_usd: float, hours_held: float = 0.0) -> float:
        fee = notional_usd * (self.perp_fee_bps / 1e4) * 2
        funding = notional_usd * (self.perp_funding_bps_per_hr / 1e4) * max(0.0, hours_held)
        return fee + funding + self.gas_usd * 2

    def position_roundtrip_usd(self, market: str, margin_usd: float,
                               leverage: float = 1.0, hours_held: float = 0.0) -> float:
        notional = margin_usd * (leverage if market == "perp" else 1.0)
        if market == "perp":
            return self.perp_roundtrip_usd(notional, hours_held)
        return self.spot_roundtrip_usd(notional)

    # ---- breakeven price move (% of notional) to cover round-trip TRADING fees ----
    def breakeven_move_pct(self, market: str) -> float:
        bps = (self.perp_fee_bps if market == "perp" else self.swap_fee_bps) * 2
        return bps / 1e4 * 100.0   # e.g. spot 0.50%, perp 0.16%

    def summary(self, deposit_usd: float = 1000.0, entry_pct_of_deposit: float = 0.0035,
                leverage: float = 10.0) -> dict:
        margin = deposit_usd * entry_pct_of_deposit
        return {
            "swap_fee_pct_per_swap": round(self.swap_fee_bps / 100, 4),
            "perp_fee_pct_per_side": round(self.perp_fee_bps / 100, 4),
            "perp_funding_pct_per_hr": round(self.perp_funding_bps_per_hr / 100, 4),
            "gas_usd_per_action": self.gas_usd,
            "breakeven_move_pct": {"spot": round(self.breakeven_move_pct("spot"), 3),
                                   "perp": round(self.breakeven_move_pct("perp"), 3)},
            "example_margin_usd": round(margin, 2),
            "example_roundtrip_usd": {
                "spot": round(self.position_roundtrip_usd("spot", margin), 4),
                "perp_at_lev": round(self.position_roundtrip_usd("perp", margin, leverage), 4),
            },
        }


_MODEL: FeeModel | None = None


def fee_model() -> FeeModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = FeeModel()
    return _MODEL
