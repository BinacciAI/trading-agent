# Binacci Agent

Reaction-based autonomous trading agent for the **BNB Chain × CoinMarketCap × Trust Wallet AI Agent Hackathon** (Track 1: Autonomous Trading Agents, Track 2: Strategy Skills).

The strategy splits trading into two strictly separated halves. **Analysis** (five simulations) decides *where* to enter: background sims maintain reference points 24/7, entry sims confirm zone and concrete level. **Execution** (deterministic engine) decides *how*: reserved-margin sizing, level-based averaging with a hard per-position cap, slot limits with smart return, a stepped trailing SL into profit, and an aggregate-drawdown kill switch. The AI layer is an executor only — it never invents or edits strategy. Numeric defaults in this repo are illustrative; production parameters load from a private overlay (`BINACCI_STRATEGY_FILE`).

## Quick start

```bash
pip install -e ".[dev,server]"

# Run the test suite
pytest

# Backtest on synthetic data (no API keys needed)
binacci backtest --symbol BNB --timeframe 15m --bars 2000

# Generate a Track 2 strategy spec (backtestable, machine-readable)
binacci spec --symbol BNB --timeframe 4h --output spec.json

# Multi-symbol paper session (slots + kill switch interplay)
binacci paper --symbols BNB,BTC,ETH,CAKE,SOL --timeframe 15m

# API + APEX server
binacci serve
```

## Sponsor stack

| Layer | Integration |
|---|---|
| L1 CMC Agent Hub | `data.py` — Data API client (quotes, OHLCV, global metrics for the macro gate), MCP endpoint for the conversational layer |
| L2 Trust Wallet Agent Kit | `venues.py` — PancakeSwap spot + BSC perps adapters over TWAK REST/MCP, self-custody signing |
| L3 BNB AI Agent SDK | `chain.py` — ERC-8004 identity, APEX (ERC-8183) paid strategy-spec jobs |

See `../docs/SETUP.md` for the full signup/wiring runbook and `../docs/ARCHITECTURE.md` for design.
