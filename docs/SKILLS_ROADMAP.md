# Binacci Skills Roadmap

Binacci's "skills" are modular, backtestable strategy/analysis units. Each one
is **(a)** a live strategy the portfolio can run and **(b)** a Track-2 CMC
Strategy Skill that emits a backtestable spec from CMC data. This roadmap maps
what to build next, why, and which sponsor surface it leans on.

Legend — effort: S(mall)/M(edium)/L(arge) · priority: ⭐ now · ◐ next · ○ later

## Shipped (v0.2)
| Skill | Type | Notes |
|---|---|---|
| Reaction (5-gate) | strategy | The patient core — references → zone → filters → macro → level |
| Momentum Breakout | strategy | Donchian breakout + retest, volume-confirmed |
| Mean Reversion | strategy | RSI/Bollinger oversold reclaim (counter-trend, no macro gate) |
| Trend Follow | strategy | EMA-stack pullback to the mid EMA |
| Volatility Squeeze | strategy | Bollinger bandwidth coil → expansion breakout |

## Tier 1 — strategy skills to add next (extend the portfolio)
| Skill | Effort | Pri | What it does | Leans on |
|---|---|---|---|---|
| **VWAP reversion** | M | ⭐ | Fade stretched deviations from rolling VWAP; band-based limit entries | CMC quotes + volume |
| **Liquidity-sweep reclaim** | M | ⭐ | Enter after a stop-run wicks a prior swing low and reclaims it | OHLCV structure |
| **Funding/derivatives skew** | M | ◐ | Bias longs/shorts when perp funding + open-interest diverge from spot | CMC derivatives endpoint |
| **Range scalper** | S | ◐ | Buy support / sell resistance inside a confirmed range; tight targets | OHLCV + S/R levels |
| **Divergence (RSI/MACD) pro** | M | ◐ | Promote the existing divergence detector into a standalone entry skill | indicators |
| **Breakout-failure fade** | M | ○ | Fade failed breakouts (false-break reversal) | OHLCV structure |
| **Pairs / ratio mean-reversion** | L | ○ | Trade BNB-relative ratios (e.g. CAKE/BNB) back to the mean | multi-symbol quotes |

## Tier 2 — analysis / signal skills (Track-2 first, feed strategies later)
| Skill | Effort | Pri | What it does | Leans on |
|---|---|---|---|---|
| **Narrative / sector rotation** | M | ⭐ | Rank CMC narratives & categories by momentum; tilt the universe toward hot sectors | CMC narratives + categories |
| **Macro regime classifier** | M | ⭐ | Label the market (risk-on / chop / risk-off) from totalCap, BTC.D, USDT.D, F&G; gate strategies by regime | CMC global metrics |
| **On-chain liquidity scout** | M | ◐ | Score BSC tokens by DEX liquidity/volume to auto-curate the tradable universe | CMC DEX/on-chain + TWAK quotes |
| **Whale / large-trade monitor** | M | ○ | Flag unusual volume & large prints as a context signal | CMC + on-chain |
| **News/event sentiment gate** | M | ○ | Suppress entries around high-impact events; tag entries with sentiment | CMC news / events |
| **Altseason timer** | S | ○ | Altcoin-season index → portfolio aggressiveness dial | CMC altseason index |

## Tier 3 — agent / execution / ops skills
| Skill | Effort | Pri | What it does | Leans on |
|---|---|---|---|---|
| **Smart order router** | M | ⭐ | Split fills, slippage caps, route the limit-touch swap optimally on PancakeSwap | TWAK |
| **Portfolio rebalancer** | M | ◐ | Keep per-strategy / per-sector exposure within target bands | engine state |
| **Drawdown sentinel** | S | ◐ | Pre-emptive de-risk (shrink size / pause) before the hard kill switch | engine state |
| **APEX job runner** | M | ◐ | Sell strategy specs as escrowed ERC-8183 jobs; x402 pay-per-call | BNB SDK + x402 |
| **Backtest-to-live promoter** | L | ○ | Auto-promote a strategy from paper to live once it clears backtest + paper thresholds | backtester |

## Hackathon priority (build order)
1. **Macro regime classifier** ⭐ — biggest risk-adjusted lift; gates the whole portfolio and showcases CMC global-metrics depth (special prize: best CMC data use).
2. **Narrative / sector rotation** ⭐ — visible "intelligence", tilts the 50+ universe, also CMC-data-rich.
3. **VWAP reversion** + **Liquidity-sweep reclaim** ⭐ — two more orthogonal strategies → more trade opportunity for the live window.
4. **Smart order router** ⭐ — best-use-of-TWAK prize; matters the moment real swaps go live.
5. **APEX job runner** ◐ — best-use-of-BNB-SDK prize + the post-hackathon revenue story.

## How each skill is packaged
Every strategy skill = a `Strategy` subclass in `agent/src/binacci/strategies.py`
(so the live portfolio can run it) **plus** an entry in `STRATEGY_META`
(`agent/src/binacci/skill.py`) and an auto-generated `SKILL.md` under `skills/`
via `skills/build_skills.py`. Analysis skills that aren't entry strategies can
ship as spec-only skills (a `market_state` + backtest contributor) before being
wired into the gate chain.
