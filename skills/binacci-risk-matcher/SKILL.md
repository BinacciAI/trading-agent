# binacci-risk-matcher

**Type:** agent (operator / risk) · **Surface:** `/risk/auto` · **Data:** live deposit + fee model

## What it does
Maps the operator's **deposit/margin** to the risk **envelope** that fits it, so slots, per-entry size, leverage and averaging are chosen *for* the capital instead of hand-tuned. It is **fee-aware**: for every mode it computes the per-entry margin, the resulting perp notional, and what fraction of that notional fixed BSC gas eats — then recommends the most diversified envelope whose entries still clear the fee floor.

The matcher **recommends by default**. The operator applies the recommendation with one tap (or enables auto-match); the agent never silently moves real-money risk.

## Why it exists
On a small deposit, "more, smaller positions" loses to fixed gas — a $7 entry pays the same ~$0.24 round-trip gas as a $700 one. The matcher encodes that economics: tiny deposits get **fewer, bigger** fee-clearing entries (Conservative); larger deposits can afford **more diversification and leverage** (Balanced → Aggressive).

## Logic
```
tiers (env-tunable: BINACCI_MATCH_TIER1=2000, _TIER2=10000):
  deposit < tier1   -> conservative   (preserve capital, few big entries)
  deposit < tier2   -> balanced       (diversify, moderate leverage)
  deposit >= tier2  -> aggressive      (capital absorbs the drawdown)

fee guard (BINACCI_FEE_FLOOR_USD=150):
  if the tier pick's perp entries fall below the fee floor,
  step DOWN toward conservative (bigger entries) until they clear it.
```
Every response carries the full per-mode table (margin, perp/spot notional, gas % of notional, max-deployed %, fee-viable flags) so the recommendation is auditable, not a black box.

## Envelopes (presets it chooses among)
| Mode | Slots | Entry % deposit | Leverage | Averaging |
|------|-------|-----------------|----------|-----------|
| Conservative | 6 | 2.45% | 10× | 1.5×, 1.0× |
| Balanced | 10 | 1.75% | 25× | 2.0×, 1.5× |
| Aggressive | 14 | 1.40% | 50× | 2.0×, 1.5× |

All three keep max-deployed capital under the 70% working band; spot is always 1×.

## API
- `GET /risk/auto` → `{recommended_mode, rationale, fits{...}, current_mode}` (read-only).
- `POST /risk/auto` → applies the recommendation as the live risk mode and persists it (same path as a manual switch).

## Module
`agent/src/binacci/riskmatch.py` — `match_risk(deposit_usd)` (pure), `riskmatch_skill_manifest()`.
