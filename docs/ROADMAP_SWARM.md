# Binacci — Swarm Roadmap: Strategies, Skills, Agents

Binacci's architecture is **many opinions → one deterministic risk engine**, perps-led,
dual-book (spot + perps), CMC-native, and now fee-aware. New work should exploit exactly
those properties: perps-native edges, the spot+perp dual book, CMC/DEX data, and the
self-optimization infra (fast backtest + sweep + persistent memory).

## 1. New Strategies (orthogonal edge)

Priority order — the top two are perps-native, low-correlation, and use the dual book:

1. **Funding-rate carry** (perps). When perp funding is extreme (crowded longs paying shorts),
   fade the crowded side. A persistent, price-pattern-independent edge. Needs on-chain funding.
2. **Spot–perp basis / cash-and-carry** (dual-book). When the perp trades rich/cheap to spot,
   capture convergence delta-neutral (spot long + perp short). Low-risk carry; uses both books
   at once — unique to Binacci's structure.
3. **BTC lead-lag** (universe). BTC breaks a level → trade the alt that hasn't caught up. Uses
   the 146-market universe + BTC.D from the regime feed.
4. **Volume-ignition** (CMC volume). Abnormal 24h-volume delta before price fully reacts — the
   volume signal is already built; this monetizes it directly.
5. **Breakout-failure fade.** Fade breakouts that fail to hold (reclaim back inside range) —
   the inverse of momentum_breakout, strong in chop. Cheap to add (mirror logic).
6. **Sentiment-extreme** (CMC Fear & Greed). Extreme fear → mean-revert long; extreme greed →
   fade. F&G is already fetched.
7. **Liquidation-cascade fade** (perps OI). Detect OI-drop + price spike (forced liquidations),
   fade the over-extension.

## 2. New Skills (CMC-data / Track-2 packages)

Each ships as a Track-2 SKILL.md + an API endpoint (like `/regime`). "Best use of CMC data":

- **Funding monitor** — on-chain perp funding extremes (pairs with strategy 1).
- **Basis monitor** — spot↔perp basis across the universe (pairs with strategy 2).
- **Liquidation / OI heatmap** — where liquidations cluster.
- **Sentiment composite** — F&G + dominance + (optional social) → one score; extends the regime agent.
- **Per-market volatility regime** — squeeze/expansion classification for position sizing.
- **Leadership / correlation** — BTC.D + cross-asset correlation → which alts to favor.
- **DEX whale-flow** (CMC DEX API) — large PancakeSwap swaps / liquidity shifts.

## 3. More Agents in the swarm? — Yes, four high-value roles

The strategy portfolio is rich; the gaps are **portfolio-level intelligence, execution quality,
self-improvement, and safety** — not more pattern-matchers.

1. **Execution-quality / routing agent** *(highest ROI given the fee findings).* Splits large
   orders, times entries to cut slippage/price-impact, picks PancakeSwap **V3 0.05% pools** vs V2,
   batches/sizes to amortize gas. Directly lifts net-of-fee P/L — the current ceiling at small size.
2. **Meta-learner / self-optimizer agent.** Periodically runs the fast-backtest sweep on the
   agent's own accumulated real data and proposes param updates (leverage, trailing, regime
   weights, sizing). Closes the loop using the sweep infra + persistent memory → a genuinely
   self-improving system.
3. **Funding/Carry agent.** Owns the funding + basis strategies and manages the delta-neutral
   book across spot and perps (different lifecycle from the directional strategies).
4. **Sentinel / anomaly agent.** Watches for de-pegs, flash crashes, oracle gaps, abnormal
   spreads → triggers halt/reconcile. Production safety beyond the drawdown kill switch.

Lower priority / later: **Treasury agent** (compound vs withdraw, keep BNB for gas),
**A2A commerce agent** (ERC-8004 + APEX: sell signals / copy-trading — monetization).

## Recommended sequencing

1. **Execution-quality agent + V3 routing** — unlocks profitability at small deposits (fixes the
   fee ceiling we just measured).
2. **Funding monitor skill + funding-rate carry strategy** — first perps-native edge.
3. **Spot–perp basis skill + carry strategy** — delta-neutral, uses the dual book.
4. **Meta-learner agent** — self-optimization on real accumulated data.
5. **Sentinel agent** — production safety.
