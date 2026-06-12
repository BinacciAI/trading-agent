# Architecture

## The thesis

Most hackathon trading agents will be "LLM decides trades from a prompt." Binacci is the opposite, and that is the institutional edge: **the AI is only an executor**. Strategy is deterministic, auditable, and replayable; the agent layer routes data, explains decisions, and sells the strategy as a service. Judges evaluating live PnL replay get a bot whose every entry carries a 5-gate audit trail.

## Two halves

```
┌──────────────────── ANALYSIS (where to enter) ────────────────────┐
│  Sim01 cold start ──┐                                             │
│  Sim02 ref updates ─┼─► ReferenceBook (per symbol × 12 TFs)       │
│  Sim03 clean refs ──┘                                             │
│                                                                   │
│  Gate chain per evaluation:                                       │
│  01 fresh reference → 02 SimA zone → 03 filters (CMD/BB/vol/RSI)  │
│  → 04 macro (totalCap+BTC.D+USDT.D via CMC) → 05 SimB level touch │
└───────────────────────────────┬───────────────────────────────────┘
                                │ EntrySignal (limit @ level, never market)
┌───────────────────── EXECUTION (how to manage) ───────────────────┐
│  reserved-margin model · fixed per-entry sizing                   │
│  level-based averaging ladder with hard per-position cap          │
│  N-slot cap + smart return (SL-in-profit releases slot)           │
│  stepped trailing SL into profit · TP scaled by timeframe         │
│  aggregate-drawdown kill switch flattens everything               │
└───────────────────────────────┬───────────────────────────────────┘
                                │ Venue protocol
        paper │ PancakeSwap spot (TWAK signing) │ BSC perps
```

## Module map (`agent/src/binacci/`)

| Module | Responsibility |
|---|---|
| `config.py` | Every strategy parameter; env/YAML overrides; AI cannot mutate |
| `models.py` | Candle, ReferencePoint, EntrySignal, Position, gate audit types |
| `indicators.py` | RSI, BB, Ichimoku, MACD, ATR, volume ratio, CMD (pluggable proprietary) |
| `levels.py` | Fib retracements/pivots, log S/R clustering, trend channels, extrema |
| `divergence.py` | Regular + hidden divergence detection on RSI |
| `simulations.py` | Sim01/02/03 (references) + SimA (zone) + SimB (level) |
| `macro.py` | totalCap/BTC.D/USDT.D gate; fails closed without data |
| `execution.py` | Margin, averaging, slots, trailing, kill switch — deterministic |
| `orchestrator.py` | 5-gate chain, pending limit management, decision traces |
| `data.py` | CMC Data API client, synthetic/CSV candle sources, TF resampler |
| `venues.py` | Venue protocol: paper, PancakeSpot (TWAK), Perps adapter |
| `chain.py` | ERC-8004 registration, APEX paid-job server (`on_job` → spec) |
| `backtest.py` | Event-driven backtests using THE SAME orchestrator+engine as live |
| `skill.py` | Track 2: backtestable spec generator + marketplace manifest |
| `api.py` | FastAPI: /status /positions /trades /traces /spec /manifest |
| `cli.py` | backtest · spec · paper · serve · register |

## Design decisions

1. **One engine, three modes.** Backtest, paper, and live all run the identical `Orchestrator` + `ExecutionEngine`. Whatever the judges see in the live window is bit-for-bit the logic in the verification backtest attached to the Track 2 spec.
2. **Limit-at-level semantics everywhere.** DEXes have no limit orders; the agent parks the SimB level internally and swaps on touch — the same semantics the backtester fills with. Slippage is then the only live-vs-backtest divergence, and it's bounded by `max_slippage_pct`.
3. **Fail closed.** No macro data → no entry. No fresh reference → no entry. Kill switch fired → nothing opens again until human reset.
4. **Decision traces as a product.** Every evaluation logs which gate blocked it. That's the demo: a live table showing the bot *refusing* to trade until the whole chain aligns — the anti-degen narrative.
5. **Semi-proprietary by construction.** Public repo = framework with illustrative defaults. Private overlay (`strategy-core`) = production parameters loaded via `BINACCI_STRATEGY_FILE`, plus the proprietary CMD formula that drops into one function (`indicators.cmd`) without touching consumers. The edge stays private; the architecture stays reviewable.

## Sponsor stack mapping (judging criteria)

| Sponsor capability | Where used |
|---|---|
| CMC Data API | Macro gate (global metrics), quotes, OHLCV history |
| CMC MCP (12 tools) | Conversational/analyst layer; cross-checks technicals (RSI, fib, S/R) |
| CMC Skills Marketplace | `skill.py` manifest + spec — Track 2 submission |
| x402 | Optional pay-per-call monetization of the spec endpoint |
| TWAK | Self-custody signing for PancakeSwap spot + perps; autonomous mode for the unattended live window |
| BNB AI Agent SDK | ERC-8004 identity; APEX escrowed strategy-spec jobs (the business model) |
| BSC | Execution venue: PancakeSwap spot + BSC perps |

## Beyond the hackathon

The APEX integration is the bridge from hackathon project to business: the agent's strategy specs and signal evaluations become escrowed, UMA-verified paid jobs that any other agent on BSC can buy. Roadmap: (1) win the live window with conservative spot config, (2) publish the skill to CMC's marketplace with x402 pricing, (3) perps venue for the leverage-native version of the margin model, (4) multi-tenant deposits (the doc's "client deposit" model) behind the same risk engine.
