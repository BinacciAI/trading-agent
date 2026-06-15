"""Macro Regime Classifier — a CMC-data analysis skill.

Reads CoinMarketCap global metrics (total market cap change, BTC dominance,
USDT/stablecoin dominance) plus the Fear & Greed index and classifies the
crypto market into one of three regimes: risk-on, chop, or risk-off. This is
the "best use of CMC data" layer — it biases the whole Binacci portfolio
(which strategies to favour, how much exposure) from a single CMC read.

Pure function of a MacroSnapshot, so it is trivially testable and replayable.
"""

from __future__ import annotations

from typing import Optional

from .macro import MacroSnapshot

REGIME_SKILL = "binacci-macro-regime-classifier"
REGIME_VERSION = "0.1.0"


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def classify_regime(macro: Optional[MacroSnapshot],
                    fear_greed: Optional[int] = None) -> dict:
    """Classify the market regime from CMC global metrics + F&G.

    Inputs (all from CoinMarketCap):
      * total market-cap change %      — rising = risk-on
      * USDT/stablecoin dominance Δ    — rising = risk-off (cash hiding)
      * BTC dominance Δ                — rising = alts bleeding (mild risk-off)
      * Fear & Greed (0-100)           — greed = risk-on
    """
    if macro is None:
        return {"regime": "unknown", "score": 0.0, "confidence": 0.0,
                "factors": {}, "note": "no CMC macro data yet"}

    fg = fear_greed if fear_greed is not None else macro.fear_greed
    cap = float(macro.total_cap_change_pct)
    btcd = float(macro.btc_dominance_change_pct)
    usdtd = float(macro.usdt_dominance_change_pct)

    f_cap = _clamp(cap / 2.0)            # +2% cap move -> full risk-on factor
    f_usdt = _clamp(-usdtd / 0.5)        # +0.5% stable dominance -> full risk-off
    f_btcd = _clamp(-btcd / 0.75) * 0.5  # BTC.D rising hurts alts (half weight)
    f_fg = _clamp((fg - 50) / 50.0) if fg is not None else 0.0

    score = _clamp(0.40 * f_cap + 0.30 * f_usdt + 0.15 * f_btcd + 0.15 * f_fg)
    regime = "risk_on" if score > 0.2 else ("risk_off" if score < -0.2 else "chop")
    guidance = {
        "risk_on": "Favour breakout/trend strategies; run full slots.",
        "chop": "Favour mean-reversion / VWAP fades; normal slots.",
        "risk_off": "Reduce exposure; lean conservative; counter-trend only.",
    }[regime]
    return {
        "regime": regime,
        "score": round(score, 3),
        "confidence": round(abs(score), 3),
        "fear_greed": fg,
        "factors": {
            "total_cap_change_pct": round(cap, 3),
            "btc_dominance_change_pct": round(btcd, 3),
            "usdt_dominance_change_pct": round(usdtd, 3),
        },
        "weights": {"total_cap": 0.40, "usdt_dominance": 0.30,
                    "btc_dominance": 0.15, "fear_greed": 0.15},
        "guidance": guidance,
        "source": "CoinMarketCap global-metrics + fear-and-greed",
    }


def regime_skill_manifest() -> dict:
    """CMC Skills Marketplace manifest for the regime classifier."""
    return {
        "name": REGIME_SKILL,
        "version": REGIME_VERSION,
        "type": "analysis",
        "title": "Macro Regime Classifier",
        "description": (
            "Classifies the crypto market regime (risk-on / chop / risk-off) from "
            "CoinMarketCap global metrics — total market-cap change, BTC dominance, "
            "USDT/stablecoin dominance — plus the CMC Fear & Greed index. One CMC read "
            "biases the entire Binacci portfolio (which strategies to favour, how much "
            "exposure to run)."
        ),
        "inputs": {"source": "CMC /v1/global-metrics/quotes/latest + /v3/fear-and-greed/latest"},
        "outputs": {"regime": "risk_on|chop|risk_off", "score": "-1..1",
                    "factors": "the CMC inputs and their weights"},
        "data_dependencies": ["CMC global metrics (totalCap, BTC.D, USDT.D)", "CMC Fear & Greed"],
        "monetization": "x402 pay-per-call and/or APEX (ERC-8183) escrowed jobs on BSC",
        "author": "Binacci / Brandon",
        "contact": "brandononchain@gmail.com",
    }
