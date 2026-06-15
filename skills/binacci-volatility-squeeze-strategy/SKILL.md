---
name: binacci-volatility-squeeze-strategy
description: >-
  Track-2 CMC Strategy Skill. Volatility Squeeze — generates a backtestable trading
  strategy spec from CoinMarketCap market data (quotes, OHLCV, global metrics).
  Ships a machine-readable, replayable spec + verification backtest, not a live
  agent. Bollinger bandwidth in a low-percentile coil, then a close above the upper band; limit parked at the breakout retest.
version: 0.2.0
---

# Volatility Squeeze — Binacci Strategy Skill

> **Track 2 (Strategy Skills).** Input: a symbol + timeframe and CMC market
> data. Output: a deterministic, **backtestable** strategy spec — rules,
> parameters, current market state, and a verification backtest run by the
> same engine as the live Binacci agent.

## Philosophy

Low volatility is potential energy; expansion releases it.

## Entry logic

Bollinger bandwidth in a low-percentile coil, then a close above the upper band; limit parked at the breakout retest.

**Gate chain:** `bandwidth_squeeze → upper_band_break → macro_ok → retest_touch`
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
| `bb_period` | `20` |
| `bb_std` | `2.0` |
| `lookback` | `120` |
| `squeeze_quantile` | `0.3` |
| `retest_band_pct` | `0.4` |
| `target_mult` | `1.5` |
| `require_macro` | `True` |

## Generate a spec

CLI:

```bash
binacci spec --strategy volatility_squeeze --symbol BNB --timeframe 4h
```

API (when the agent server is running):

```bash
curl "http://localhost:8000/spec?strategy=volatility_squeeze&symbol=BNB&timeframe=4h"
```

Python:

```python
from binacci.config import StrategyConfig, Timeframe
from binacci.skill import generate_strategy_spec
spec = generate_strategy_spec(StrategyConfig(), symbol="BNB",
                              tf=Timeframe.H4, strategy="volatility_squeeze")
```

## Output shape

```jsonc
{
  "skill": "binacci-volatility-squeeze-strategy",
  "strategy_name": "volatility_squeeze",
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
