"""Spot–perp basis carry — the delta-neutral sibling of funding_carry.

When the perp trades at a sustained PREMIUM to spot, the basis is a paid carry:
go SHORT the rich perp and LONG the cheap spot in equal notional. Price moves
cancel (delta-neutral); the position earns the basis as it converges plus the
funding the crowded longs pay. Uses BOTH books at once — unique to Binacci.

Premium-only by design: the spot leg can only be long, so a true delta-neutral
hedge exists only for the short-perp (premium) side. The discount/directional
case is covered by funding_carry.
"""

from __future__ import annotations

from .funding import basis_implied_funding  # noqa: F401  (re-export for callers)

BASIS_SKILL = "binacci-basis-carry"
BASIS_VERSION = "0.1.0"


def expected_carry_pct(basis_pct: float, funding_bps_per_hr: float, hours: float) -> float:
    """Rough carry over a hold: basis convergence + funding collected."""
    return basis_pct + (funding_bps_per_hr / 100.0) * max(0.0, hours)


def basis_skill_manifest() -> dict:
    return {
        "name": BASIS_SKILL, "version": BASIS_VERSION, "type": "strategy",
        "title": "Spot–Perp Basis Carry (delta-neutral)",
        "summary": "On a perp premium to spot: short the perp + long equal-notional spot. "
                   "Delta-neutral; earns basis convergence + funding. Uses both books.",
        "inputs": ["perp_mark (on-chain)", "spot_quote (CoinMarketCap)"],
        "market": "perp+spot", "delta_neutral": True, "both_ways": False,
        "source": "on-chain perp mark + CoinMarketCap spot",
    }
