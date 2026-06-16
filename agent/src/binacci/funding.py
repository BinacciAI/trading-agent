"""Perps funding / basis — a CMC-data analysis skill + carry signal.

Funding can't be read directly on the free plan, so Binacci derives it from
the on-chain perp MARK vs the SPOT quote: a perp trading at a premium to spot
means longs are paying funding (crowded longs); a discount means crowded
shorts. The carry edge is to fade the crowded side. The live loop supplies
marks; in paper (mark == spot) the basis is zero and the strategy stays idle.
"""

from __future__ import annotations

FUNDING_SKILL = "binacci-funding-carry"
FUNDING_VERSION = "0.1.0"


def basis_implied_funding(perp_mark: float, spot: float) -> float:
    """Perp premium/discount vs spot, in percent. Proxy for funding pressure."""
    if not spot:
        return 0.0
    return (perp_mark - spot) / spot * 100.0


def classify_funding(funding_pct: float, threshold_pct: float = 0.05) -> dict:
    if funding_pct > threshold_pct:
        state, fade = "crowded_long", "short"
    elif funding_pct < -threshold_pct:
        state, fade = "crowded_short", "long"
    else:
        state, fade = "neutral", None
    return {"funding_pct": round(funding_pct, 4), "state": state, "fade_side": fade,
            "extreme": abs(funding_pct) >= threshold_pct}


def funding_skill_manifest() -> dict:
    return {
        "name": FUNDING_SKILL, "version": FUNDING_VERSION, "type": "strategy",
        "title": "Perps Funding / Basis Carry",
        "summary": "Derives perp funding pressure from on-chain mark vs CMC spot "
                   "and fades the crowded side (premium -> short, discount -> long).",
        "inputs": ["perp_mark (on-chain)", "spot_quote (CoinMarketCap)"],
        "signal": "basis_implied_funding -> classify_funding(threshold)",
        "market": "perp", "both_ways": True,
        "source": "on-chain perp mark + CoinMarketCap spot",
    }
