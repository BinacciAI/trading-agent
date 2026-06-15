---
name: binacci-reaction-strategy
description: >-
  Track-2 CMC Strategy Skill. Reaction (5-gate) — generates a backtestable trading
  strategy spec from CoinMarketCap market data (quotes, OHLCV, global metrics).
  Ships a machine-readable, replayable spec + verification backtest, not a live
  agent. Patient, high-conviction. Fib/divergence/Bollinger zone, confirmed by CMD+RSI+volume, gated by macro, filled at a concrete log-S/R or fib level.
version: 0.2.0
---

# Reaction (5-gate) — Binacci Strategy Skill

> **Track 2 (Strategy Skills).** Input: a symbol + timeframe and CMC market
> data. Output: a deterministic, **backtestable** strategy spec — rules,
> parameters, current market state, and a verification backtest run by the
> same engine as the live Binacci agent.

## Philosophy

Catch market reactions, not movements. References -> confirmations -> filters -> macro -> level. Short guaranteed targets.

## Entry logic

Patient, high-conviction. Fib/divergence/Bollinger zone, confirmed by CMD+RSI+volume, gated by macro, filled at a concrete log-S/R or fib level.

**Gate chain:** `fresh_reference → entry_zone → filters_ok → macro_ok → level_touch`
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
| `filters.rsi_period` | `14` |
| `filters.rsi_oversold` | `32.0` |
| `filters.rsi_overbought` | `68.0` |
| `filters.bollinger_period` | `20` |
| `filters.bollinger_std` | `2.0` |
| `filters.volume_lookback` | `20` |
| `filters.volume_min_ratio` | `1.15` |
| `filters.cmd_fast` | `9` |
| `filters.cmd_slow` | `26` |
| `filters.ichimoku_conversion` | `9` |
| `filters.ichimoku_base` | `26` |
| `filters.ichimoku_span_b` | `52` |
| `fib_levels` | `[0.236, 0.382, 0.5, 0.618, 0.786]` |
| `extrema_window` | `12` |
| `level_tolerance_pct` | `0.15` |

## Generate a spec

CLI:

```bash
binacci spec --strategy reaction --symbol BNB --timeframe 4h
```

API (when the agent server is running):

```bash
curl "http://localhost:8000/spec?strategy=reaction&symbol=BNB&timeframe=4h"
```

Python:

```python
from binacci.config import StrategyConfig, Timeframe
from binacci.skill import generate_strategy_spec
spec = generate_strategy_spec(StrategyConfig(), symbol="BNB",
                              tf=Timeframe.H4, strategy="reaction")
```

## Output shape

```jsonc
{
  "skill": "binacci-reaction-strategy",
  "strategy_name": "reaction",
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
