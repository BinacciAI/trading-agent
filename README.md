# Binacci — Binary Agentic Trading

Autonomous trading agent by **BinacciAI** for the **BNB Chain × CoinMarketCap × Trust Wallet AI Agent Hackathon** (June 3–21, 2026), built to outlive it as a business.

**Philosophy:** AI trading agents hallucinate trades or blow up. Binacci separates *brains from hands* — a deterministic, auditable strategy engine decides; the AI only executes. CMC signals in, Trust Wallet self-custody out, on BNB Chain. Every entry passes a multi-gate audit. The AI decides nothing and edits nothing.

## Layout

```
agent/        Python core — strategy portfolio, 5 simulations, deterministic
              risk engine, backtester, Track-2 skill family, FastAPI + APEX server
dashboard/    Next.js live console (command center, strategies, backtests, risk, settings)
skills/       Track-2 CMC Strategy Skills — installable SKILL.md packages, one per strategy
docs/         SETUP.md · ARCHITECTURE.md · HACKATHON.md · SKILLS_ROADMAP.md
```

## What's new (v0.2)

- **Strategy portfolio (5 concurrent strategies).** Reaction (the patient 5-gate core) + Momentum Breakout + Mean Reversion + Trend Follow + Volatility Squeeze — orthogonal opinions, all feeding one risk engine. Positions are unique per `(market, timeframe, strategy)`, so a quiet day for one is a busy day for another.
- **50+ markets on BNB.** A BSC-ecosystem-weighted universe (BSC-native blue chips + the deepest Binance-Peg majors), analysed across six live timeframes.
- **Risk modes.** Conservative / Balanced / Aggressive scale the number of concurrent positions and per-entry size *together* (15 / 30 / 50 slots), so a wider book stays just as conservative — same 30% kill switch, same 30% reserve. Switchable live.
- **Book switches.** Activate the **Spot** and/or **Perps** book independently from the dashboard **Settings → Live Tuning** controls (or `POST /books`). A deactivated book takes no new positions and is flattened immediately; the choice persists across redeploys. A one-click **Close all positions** (`POST /positions/close`) flattens the book at market.
- **Track-2 skill family.** Per-strategy and portfolio backtestable specs, plus installable `SKILL.md` packages under `skills/`.
- **Credit-aware data layer.** Real per-bar volume from CMC 24h-volume deltas, decoupled macro / Fear-&-Greed cadences, and a live credit-burn estimate.

## How it trades

**Analysis.** Three background simulations maintain per-coin reference points 24/7 (Fibonacci structures, divergences, local extrema). On top of those, five strategies each scan every market and timeframe and propose a limit entry where they want to be a resting buyer. Whatever a strategy proposes, the entry still passes the shared gates — fresh reference (where required) → the strategy's own zone/filters → macro gate (totalCap + BTC.D + USDT.D, per-strategy) → level touch. Entries are always limit-at-level, never a market chase.

**Execution (deterministic engine).** A reserved-margin model with strict per-entry sizing, level-based averaging with a hard per-position cap, a mode-scaled cap on simultaneous positions with smart slot return, a stepped trailing stop that walks into profit, timeframe-scaled take-profits, and an aggregate-drawdown kill switch that flattens everything. The AI proposes; the engine disposes.

> **Note on parameters:** all numeric values in this repository are *illustrative defaults*. Production parameters — and the proprietary CMD filter — load from a private overlay via `BINACCI_STRATEGY_FILE` (see the private `strategy-core` repo).

## Sponsor stack (all three layers)

- **CoinMarketCap** — Data API + MCP for quotes, technicals, and the macro gate; Skills Marketplace for the Track-2 specs; x402 monetization.
- **Trust Wallet Agent Kit** — self-custody local signing, autonomous mode for the unattended Jun 22–28 live window; PancakeSwap spot (BSC perps on the roadmap).
- **BNB AI Agent SDK** — ERC-8004 on-chain identity; APEX (ERC-8183) escrowed paid strategy-spec jobs — the post-hackathon revenue path.

## Quick start

```bash
cd agent && pip install -e ".[dev,server]"
pytest                                                   # 27 tests
python -m binacci.cli strategies                         # the 5-strategy catalog
python -m binacci.cli backtest --symbol BNB --timeframe 15m
python -m binacci.cli spec --portfolio --symbol BNB --timeframe 4h --output spec.json
BINACCI_RISK_MODE=balanced python -m binacci.cli serve   # API :8000
cd ../dashboard && npm install && npm run dev            # console :3000
```

### Risk modes

```bash
BINACCI_RISK_MODE=conservative   # 15 slots · larger entries · widest margin
BINACCI_RISK_MODE=balanced       # 30 slots · default · active across many markets
BINACCI_RISK_MODE=aggressive     # 50 slots · smallest entries · max market coverage
```

…or switch live from the dashboard **Settings** page (`POST /risk/mode`).

Start with `docs/SETUP.md` — DoraHacks registration, CMC key, TWAK, and wallet, in order.

---
© 2026 BinacciAI. All rights reserved. The strategy framework is published for hackathon evaluation; production strategy parameters and the CMD filter remain proprietary.
