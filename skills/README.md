# Binacci Strategy Skills (CMC Hackathon — Track 2)

A family of **backtestable strategy skills** for the BNB Chain × CoinMarketCap
× Trust Wallet AI Agent Hackathon. Each skill turns CMC market data into a
deterministic, replayable strategy spec + verification backtest — "quant
research", not a live agent. All specs are produced by the **same engine** the
live Binacci Track-1 agent trades with, so a spec's backtest is exactly what
the agent would have done.

## Skills

| Skill | id | macro gate | philosophy |
|---|---|---|---|
| [Reaction (5-gate)](binacci-reaction-strategy/SKILL.md) | `reaction` | yes | Catch market reactions, not movements. References -> confirmations -> filters -> macro -> level. Short guaranteed targets. |
| [Momentum Breakout](binacci-momentum-breakout-strategy/SKILL.md) | `momentum_breakout` | yes | Trend ignition leaves a footprint: a clean break of range with volume. |
| [Mean Reversion (oversold reclaim)](binacci-mean-reversion-strategy/SKILL.md) | `mean_reversion` | no | Capitulation overshoots; the snap back to the mean is tradable. |
| [Trend Follow (EMA-stack pullback)](binacci-trend-follow-strategy/SKILL.md) | `trend_follow` | yes | The trend is the edge; buy the pullback, not the breakout. |
| [Volatility Squeeze](binacci-volatility-squeeze-strategy/SKILL.md) | `volatility_squeeze` | yes | Low volatility is potential energy; expansion releases it. |
| [VWAP Reversion](binacci-vwap-reversion-strategy/SKILL.md) | `vwap_reversion` | no | Price rubber-bands back to where volume actually traded. |
| [Liquidity Sweep Reclaim](binacci-liquidity-sweep-strategy/SKILL.md) | `liquidity_sweep` | no | Stop-runs trap late sellers; the reclaim is the reversal. |

Plus a **portfolio** spec that runs every strategy together:

```bash
binacci spec --portfolio --symbol BNB --timeframe 4h
curl "http://localhost:8000/spec?strategy=portfolio&symbol=BNB&timeframe=4h"
```

## Why a family, not one strategy

One strategy is one opinion. Binacci runs a portfolio of orthogonal
strategies over every (symbol, timeframe) stream, each proposing limit
entries into the same hard risk engine. More independent reasons to be in a
market = a wider opportunity surface, with the slot cap and kill switch still
bounding total exposure. Positions are keyed per `(symbol, timeframe,
strategy)`, so the strategies never collide.

## Regenerate these docs

```bash
PYTHONPATH=agent/src python skills/build_skills.py
```

*Generated from `binacci.skill.STRATEGY_META` — edit the code, not the docs.*
