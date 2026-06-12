# Binacci — Binary Agentic Trading

Autonomous trading agent by **BinacciAI** for the **BNB Chain × CoinMarketCap × Trust Wallet AI Agent Hackathon** (June 3–21, 2026), built to outlive it as a business.

**Philosophy:** we don't guess the market — we catch it in reactions. References → confirmations → filters. Short, guaranteed targets. The AI is only an executor; it decides nothing and edits nothing.

## Layout

```
agent/        Python core — 5 simulations, deterministic risk engine,
              backtester, Track 2 skill, FastAPI + APEX server
dashboard/    Next.js live console (equity, positions, 5-gate decision traces)
docs/         SETUP.md (signup runbook) · ARCHITECTURE.md · HACKATHON.md (10-day plan)
```

## How it trades

**Analysis (5 simulations).** Three background sims maintain per-coin reference points 24/7 across 12 timeframes (Fibonacci structures, divergences, local extrema). Two entry sims confirm the zone and pick the concrete level. Every entry passes a 5-gate chain — fresh reference → zone → indicator filters → macro gate (totalCap + BTC.D + USDT.D) → level touch. Any gate fails: no entry. Entries are always limit-at-level, never market.

**Execution (deterministic engine).** A reserved-margin model with strict per-entry sizing, level-based averaging with a hard per-position cap, a fixed cap on simultaneous positions with smart slot return, a stepped trailing stop that walks into profit, timeframe-scaled take-profits, and an aggregate-drawdown kill switch that flattens everything.

> **Note on parameters:** all numeric values in this repository are *illustrative defaults*. Production parameters — and the proprietary CMD filter — load from a private overlay via `BINACCI_STRATEGY_FILE` (see the private `strategy-core` repo).

## Sponsor stack (all three layers)

- **CoinMarketCap** — Data API + MCP for quotes, technicals, and the macro gate; Skills Marketplace for the Track 2 spec; x402 monetization.
- **Trust Wallet Agent Kit** — self-custody local signing, autonomous mode for the unattended Jun 22–28 live window; PancakeSwap spot + BSC perps venues.
- **BNB AI Agent SDK** — ERC-8004 on-chain identity; APEX (ERC-8183) escrowed paid strategy-spec jobs — the post-hackathon revenue path.

## Quick start

```bash
cd agent && pip install -e ".[dev,server]"
pytest                                                  # 17 tests
python -m binacci.cli backtest --symbol BNB --timeframe 15m
python -m binacci.cli spec --symbol BNB --timeframe 4h --output spec.json
python -m binacci.cli serve                             # API :8000
cd ../dashboard && npm install && npm run dev           # console :3000
```

Start with `docs/SETUP.md` — DoraHacks registration, CMC key, TWAK, and wallet, in order.

---
© 2026 BinacciAI. All rights reserved. The strategy framework is published for hackathon evaluation; production strategy parameters and the CMD filter remain proprietary.
