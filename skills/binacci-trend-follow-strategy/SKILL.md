---
name: binacci-trend-follow-strategy
description: >-
  Track-2 CMC Strategy Skill. Trend Follow (EMA-stack pullback) — generates a backtestable trading
  strategy spec from CoinMarketCap market data (quotes, OHLCV, global metrics).
  Ships a machine-readable, replayable spec + verification backtest, not a live
  agent. Fast/mid/slow EMAs stacked bullishly with a non-declining slow EMA; limit parked at the mid EMA pullback. Trailing SL lets it run.
version: 0.2.0
---

# Trend Follow (EMA-stack pullback) — Binacci Strategy Skill

> **Track 2 (Strategy Skills).** Input: a symbol + timeframe and CMC market
> data. Output: a deterministic, **backtestable** strategy spec — rules,
> parameters, current market state, and a verification backtest run by the
> same engine as the live Binacci agent.

## Philosophy

The trend is the edge; buy the pullback, not the breakout.

## Entry logic

Fast/mid/slow EMAs stacked bullishly with a non-declining slow EMA; limit parked at the mid EMA pullback. Trailing SL lets it run.

**Gate chain:** `ema_stack_aligned → pullback_to_mid → macro_ok → level_touch`
**Macro gate:** required.

## Shared risk model (identical across every Binacci strategy)

Every strategy feeds ONE deterministic execution engine — the AI is an
executor, never a risk-taker:

- 30/70 margin model: 30% of deposit reserved, entry = 0.35% of deposit.
- Averaging x4 then x2, **only at a level and only while in drawdown** (~3% position cap).
- 5 concurrent slots, with smart slot return when the trailing SL is already green.
- Stepped trailing SL (trigger +0.4% → SL +0.2%, then +0.1% steps) — a position almost cannot close red.
- 30% aggregate-drawdown kill switch closes everything.
- Positions are unique per `(symbol, timeframe, strategy)`, so strategies run concurrently without colliding.

## Parameters

| Parameter | Default |
|---|---|
| `ema_fast` | `8` |
| `ema_mid` | `21` |
| `ema_slow` | `55` |
| `pullback_tolerance_pct` | `0.8` |
| `target_mult` | `1.25` |
| `require_macro` | `True` |

## Generate a spec

CLI:

```bash
binacci spec --strategy trend_follow --symbol BNB --timeframe 4h
```

API (when the agent server is running):

```bash
curl "http://localhost:8000/spec?strategy=trend_follow&symbol=BNB&timeframe=4h"
```

Python:

```python
from binacci.config import StrategyConfig, Timeframe
from binacci.skill import generate_strategy_spec
spec = generate_strategy_spec(StrategyConfig(), symbol="BNB",
                              tf=Timeframe.H4, strategy="trend_follow")
```

## Output shape

```jsonc
{
  "skill": "binacci-trend-follow-strategy",
  "strategy_name": "trend_follow",
  "strategy":   { "entry_chain": [...], "parameters": {...}, "execution": {...} },
  "market_state": { "price": ..., "reference": ..., "proposal": { "in_setup": true|false, "level_price": ... } },
  "backtest":   { "trades": N, "win_rate_pct": ..., "return_pct": ..., "max_drawdown_pct": ..., "sharpe": ... },
  "provenance": { "config_fingerprint": "…", "engine": "binacci.backtest (same engine as live agent)" }
}
```

## Data dependencies (CMC L1)

- `v2/cryptocurrency/quotes/latest` — price + 24h volume
- `v2/cryptocurrency/ohlcv/historical` — candles
- `v1/global-metrics/quotes/latest` — totalCap, BTC.D, USDT.D (macro gate)
- CMC MCP technicals (RSI / Fibonacci / support-resistance) — cross-check

## Monetization (optional)

x402 pay-per-call and/or APEX (ERC-8183) escrowed jobs on BSC.

---
*Binacci strategy family · v0.2.0 · contact: brandononchain@gmail.com*
