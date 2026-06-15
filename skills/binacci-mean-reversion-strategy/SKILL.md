---
name: binacci-mean-reversion-strategy
description: >-
  Track-2 CMC Strategy Skill. Mean Reversion (oversold reclaim) — generates a backtestable trading
  strategy spec from CoinMarketCap market data (quotes, OHLCV, global metrics).
  Ships a machine-readable, replayable spec + verification backtest, not a live
  agent. RSI deeply oversold AND price pierced the lower Bollinger band, then reclaimed it; limit parked at the band. Explicitly counter-trend — no macro light required.
version: 0.2.0
---

# Mean Reversion (oversold reclaim) — Binacci Strategy Skill

> **Track 2 (Strategy Skills).** Input: a symbol + timeframe and CMC market
> data. Output: a deterministic, **backtestable** strategy spec — rules,
> parameters, current market state, and a verification backtest run by the
> same engine as the live Binacci agent.

## Philosophy

Capitulation overshoots; the snap back to the mean is tradable.

## Entry logic

RSI deeply oversold AND price pierced the lower Bollinger band, then reclaimed it; limit parked at the band. Explicitly counter-trend — no macro light required.

**Gate chain:** `rsi_oversold → bb_lower_pierce → reclaim → level_touch`
**Macro gate:** not required (counter-trend).

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
| `rsi_oversold` | `30.0` |
| `rsi_overbought` | `70.0` |
| `bb_period` | `20` |
| `bb_std` | `2.0` |
| `require_reclaim` | `True` |
| `target_mult` | `1.0` |
| `require_macro` | `False` |

## Generate a spec

CLI:

```bash
binacci spec --strategy mean_reversion --symbol BNB --timeframe 4h
```

API (when the agent server is running):

```bash
curl "http://localhost:8000/spec?strategy=mean_reversion&symbol=BNB&timeframe=4h"
```

Python:

```python
from binacci.config import StrategyConfig, Timeframe
from binacci.skill import generate_strategy_spec
spec = generate_strategy_spec(StrategyConfig(), symbol="BNB",
                              tf=Timeframe.H4, strategy="mean_reversion")
```

## Output shape

```jsonc
{
  "skill": "binacci-mean-reversion-strategy",
  "strategy_name": "mean_reversion",
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
