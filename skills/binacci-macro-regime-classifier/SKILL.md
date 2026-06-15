---
name: binacci-macro-regime-classifier
description: >-
  CMC analysis skill. Classifies the crypto market regime (risk-on / chop /
  risk-off) from CoinMarketCap global metrics — total market-cap change, BTC
  dominance, USDT/stablecoin dominance — plus the CMC Fear & Greed index. One
  CMC read biases the whole Binacci portfolio.
version: 0.1.0
---

# Macro Regime Classifier — Binacci CMC Skill

> Best-use-of-CMC-data layer. A single read of CoinMarketCap's global metrics
> tells the agent whether the market is risk-on, chopping, or risk-off — and
> the portfolio leans accordingly.

## Inputs (all CoinMarketCap)
- Total market-cap change % (rising → risk-on)
- USDT / stablecoin dominance Δ (rising → risk-off, cash hiding)
- BTC dominance Δ (rising → alts bleeding, mild risk-off)
- Fear & Greed index 0–100 (greed → risk-on)

## Output
```json
{ "regime": "risk_on|chop|risk_off", "score": -1.0..1.0, "confidence": 0..1,
  "factors": { "total_cap_change_pct": …, "btc_dominance_change_pct": …, "usdt_dominance_change_pct": … },
  "guidance": "which strategies to favour and how much exposure" }
```

## Scoring
`score = 0.40·capΔ + 0.30·(−usdtΔ) + 0.15·(−btcΔ)·½ + 0.15·F&G`, clamped to [-1,1].
`risk_on` if score > 0.2, `risk_off` if < −0.2, else `chop`.

## Use it
- Live: `GET /regime` on the agent API.
- Programmatic: `from binacci.regime import classify_regime`.

## Guidance mapping
- **risk_on** → favour breakout/trend strategies; run full slots.
- **chop** → favour mean-reversion / VWAP fades; normal slots.
- **risk_off** → reduce exposure; counter-trend only.

*Data: CMC `/v1/global-metrics/quotes/latest` + `/v3/fear-and-greed/latest`. Monetizable via x402 / APEX.*
