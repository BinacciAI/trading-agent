"""Margin → risk-mode matcher (swarm agent).

Picks the risk envelope that fits the operator's deposit instead of
hand-tuning slots and entry size. It is *transparent and fee-aware*: for
every mode it reports the per-entry margin, the resulting perp notional, and
what fraction of that notional fixed BSC gas eats — then recommends the most
diversified envelope whose entries still clear the fee floor at this deposit.

Recommend-by-default: :func:`match_risk` is pure and side-effect free. The API
layer applies the recommendation only when the operator taps "Match" (or turns
on auto-match), so the agent never silently moves real-money risk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict

from .config import RiskMode, RISK_PRESETS, StrategyConfig
from .fees import FeeModel


def _f(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env, default))
    except (TypeError, ValueError):
        return default


@dataclass
class ModeFit:
    mode: str
    slots: int
    leverage: float
    entry_pct_of_deposit: float
    entry_margin_usd: float
    perp_notional_usd: float
    spot_notional_usd: float
    perp_gas_pct: float          # fixed gas as % of perp notional (lower = better)
    spot_gas_pct: float
    max_deployed_pct: float
    perp_fee_viable: bool        # perp entries clear the fee floor
    spot_fee_viable: bool


def _mode_fit(mode: RiskMode, deposit_usd: float, gas_roundtrip: float,
              fee_floor_usd: float) -> ModeFit:
    cfg = StrategyConfig()
    cfg.apply_risk_mode(mode)
    epd = cfg.margin.entry_pct_of_deposit
    margin = epd * deposit_usd
    lev = cfg.perps_leverage
    perp_notl = margin * lev
    spot_notl = margin
    cap = cfg.margin.position_cap_pct()
    return ModeFit(
        mode=mode.value,
        slots=cfg.risk.max_positions,
        leverage=lev,
        entry_pct_of_deposit=round(epd, 5),
        entry_margin_usd=round(margin, 2),
        perp_notional_usd=round(perp_notl, 2),
        spot_notional_usd=round(spot_notl, 2),
        perp_gas_pct=round(gas_roundtrip / perp_notl * 100, 4) if perp_notl else 999.0,
        spot_gas_pct=round(gas_roundtrip / spot_notl * 100, 4) if spot_notl else 999.0,
        max_deployed_pct=round(cap * cfg.risk.max_positions * 100, 2),
        perp_fee_viable=perp_notl >= fee_floor_usd,
        spot_fee_viable=spot_notl >= fee_floor_usd,
    )


def match_risk(deposit_usd: float) -> dict:
    """Recommend a risk mode for ``deposit_usd``.

    Tiers (override via BINACCI_MATCH_TIER1 / _TIER2):
      • < tier1 ($2,000)   → conservative — preserve capital, few big entries.
      • < tier2 ($10,000)  → balanced     — diversify at moderate leverage.
      • ≥ tier2            → aggressive    — capital can absorb the drawdown.

    The tier pick is then *fee-checked*: if the picked mode's perp entries fall
    below the fee floor, we step DOWN to the mode with bigger entries that does
    clear it (conservative has the largest entries). The result carries the
    full per-mode table so the rationale is auditable, not a black box.
    """
    deposit_usd = max(0.0, float(deposit_usd))
    gas = FeeModel().gas_usd * 2.0        # open + close
    floor = _f("BINACCI_FEE_FLOOR_USD", 150.0)
    tier1 = _f("BINACCI_MATCH_TIER1", 2000.0)
    tier2 = _f("BINACCI_MATCH_TIER2", 10000.0)

    order = [RiskMode.CONSERVATIVE, RiskMode.BALANCED, RiskMode.AGGRESSIVE]
    fits = {m.value: _mode_fit(m, deposit_usd, gas, floor) for m in order}

    if deposit_usd < tier1:
        pick = RiskMode.CONSERVATIVE
    elif deposit_usd < tier2:
        pick = RiskMode.BALANCED
    else:
        pick = RiskMode.AGGRESSIVE

    # Fee guard: never recommend an envelope whose perp entries are gas-dead.
    # Conservative carries the biggest entries, so stepping toward it recovers
    # viability at tiny deposits.
    guard_note = ""
    while pick != RiskMode.CONSERVATIVE and not fits[pick.value].perp_fee_viable:
        prev = pick
        pick = order[order.index(pick) - 1]
        guard_note = (f"{prev.value} entries (${fits[prev.value].perp_notional_usd:.0f} "
                      f"notional) fall below the ${floor:.0f} fee floor — stepped down "
                      f"to {pick.value} for bigger, fee-clearing entries.")

    f = fits[pick.value]
    spot_warn = ("" if f.spot_fee_viable else
                 f" Spot entries (${f.spot_notional_usd:.0f}) are below the fee floor at this "
                 f"deposit, so the fee gate will skip most spot setups and perps carry the book.")
    rationale = (
        f"Deposit ${deposit_usd:,.0f} → {pick.value.upper()}: {f.slots} slots, "
        f"{f.leverage:.0f}× perps, ${f.entry_margin_usd:.0f} margin per entry → "
        f"${f.perp_notional_usd:,.0f} perp notional (gas {f.perp_gas_pct:.3f}% of notional), "
        f"~{f.max_deployed_pct:.0f}% max deployed."
        + (f" {guard_note}" if guard_note else "")
        + spot_warn
    )

    return {
        "deposit_usd": deposit_usd,
        "recommended_mode": pick.value,
        "fee_floor_usd": floor,
        "gas_roundtrip_usd": round(gas, 4),
        "tiers": {"tier1": tier1, "tier2": tier2},
        "rationale": rationale,
        "fits": {k: asdict(v) for k, v in fits.items()},
    }


def riskmatch_skill_manifest() -> dict:
    """Self-describing manifest for the swarm/skills surface."""
    return {
        "name": "binacci-risk-matcher",
        "kind": "agent",
        "summary": "Maps deposit/margin to the fee-viable risk envelope.",
        "inputs": ["deposit_usd"],
        "outputs": ["recommended_mode", "rationale", "per-mode fee table"],
        "applies": "recommend by default; operator applies with one tap",
    }
