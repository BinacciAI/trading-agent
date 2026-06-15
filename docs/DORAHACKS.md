# DoraHacks BUIDL — refined profile + milestones

## Profile

**Name:** Binacci AI

**Tagline (one line):**
> Brains separated from hands: a deterministic strategy engine decides, the AI only executes.

**Description (refined — replace the current one):**
> AI trading agents hallucinate trades or blow up. Binacci separates brains from hands: a deterministic, auditable strategy engine decides; the AI only executes — CMC signals in, Trust Wallet self-custody out, on BNB Chain.
>
> A portfolio of five orthogonal strategies (reaction, breakout, mean-reversion, trend, squeeze) runs across 50+ BNB markets and six timeframes at once. Every entry passes a multi-gate audit — fresh reference → zone → filters → macro → level touch — and is sized by a hard risk engine: reserved margin, per-position cap, mode-scaled slot limit, stepped trailing stop, and a 30% aggregate-drawdown kill switch. The AI never overrides a single rule.
>
> Track 1: the live agent. Track 2: a family of CMC Strategy Skills that turn market data into backtestable specs — same engine as the live agent, so a spec's backtest is exactly what Binacci would have done.

**Tags:** Crypto / Web3 · BNB Chain · DeFi · Crypto-AI · Trading Agent · CoinMarketCap · Trust Wallet

**Links:** github.com/BinacciAI · binacci.ai · 𝕏 @binacciai

## Milestones (timeline — replace/extend the current three)

1. **2026/06/11 · Onboarding** — BUIDL created on DoraHacks; registered for the hackathon; CMC API key, Trust Wallet Agent Kit, and BSC wallet provisioned.
2. **2026/06/12 · Architecture locked** — Brains/hands split shipped: deterministic risk engine (reserved margin, averaging, slot cap, stepped trailing SL, kill switch) with the AI as executor only. 27 passing tests.
3. **2026/06/13 · Live on BNB** — Agent deployed (Railway) + dashboard (Vercel); polling CMC, building candles, running the gate chain on real BNB market data in paper mode.
4. **2026/06/14 · Strategy portfolio + 50+ markets** — Five concurrent strategies live; universe expanded to 50+ BSC markets; risk modes (Conservative/Balanced/Aggressive) added; Track-2 CMC Strategy Skills published (one backtestable spec per strategy). Dashboard: Strategies, Backtests, and Settings pages.
5. **2026/06/19 · Mainnet rehearsal** — First dust-sized PancakeSwap swap via Trust Wallet Agent Kit on BSC mainnet; ERC-8004 identity registered; APEX (ERC-8183) paid-spec endpoint live.
6. **2026/06/20 · Demo + freeze prep** — Demo video; spec-marketplace submission finalized; parameters frozen.
7. **2026/06/21 · Submission lock** — Auto-deploy off; agent armed for the live window.
8. **2026/06/22–28 · Live trading window** — Autonomous run under judging; real-market PnL tracked across 50+ markets.

## Submission checklist
- [ ] Both tracks linked (Track 1 agent + Track 2 skills) in the BUIDL.
- [ ] GitHub repo public, README current, dashboard screenshots attached.
- [ ] Demo video (≤ 3 min): the brains/hands split, the gate audit, the live dashboard, a Track-2 spec.
- [ ] Sponsor-stack callouts (CMC + TWAK + BNB SDK) explicit — special prizes are stackable.
- [ ] Wallet funded for the live window; risk mode set to Balanced.
