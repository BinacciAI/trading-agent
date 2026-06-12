# Setup Runbook — from zero to submitted

You said you have nothing set up yet. Do these in order; items 1–3 today.

## 1. Register for the hackathon (10 min)

1. Go to https://dorahacks.io/hackathon/bnbhack-twt-cmc/ and register (solo is fine, 18+).
2. Join the builder Telegram: https://t.me/+MhiOLT0YUnlmNWFk — mentor office hours are weekly; ask TWAK/perps questions there early.
3. Note the deadline: **submission locks June 21, 12:00 UTC**. Track 1 live trading window is **June 22–28** (your agent must run unattended that week).

## 2. CMC Pro API key (10 min)

1. Sign up at https://pro.coinmarketcap.com/login → copy the API key from the dashboard.
2. Put it in `agent/.env`:
   ```
   BINACCI_CMC_API_KEY=your-key
   ```
3. The same key drives the CMC MCP (`https://mcp.coinmarketcap.com/mcp`, header `X-CMC-MCP-API-KEY`). Add it to Claude/Cursor for interactive signal work:
   ```json
   { "mcpServers": { "cmc-mcp": { "url": "https://mcp.coinmarketcap.com/mcp",
       "headers": { "X-CMC-MCP-API-KEY": "your-key" } } } }
   ```
4. Free tier limits matter — hackathon winners get CMC Pro credits, but during build, throttle: the agent polls global metrics every 5 min and quotes per loop; OHLCV history endpoints may need the Hobbyist plan ($29/mo). Decision: try free tier first, upgrade only if `ohlcv/historical` 403s.

## 3. Wallet + Trust Wallet Agent Kit (30–60 min)

1. Install Trust Wallet, create a **fresh wallet dedicated to the agent** (never your main wallet).
2. Get TWAK from https://portal.trustwallet.com/ — install the agent kit, run its local endpoint, note the URL into `BINACCI_TWAK_ENDPOINT`.
3. Fork/read `tw-agent-skills` (reference agents) — run one on **BSC testnet** day one.
4. Testnet funds: https://www.bnbchain.org/en/testnet-faucet for tBNB.
5. Mainnet (only before Jun 21, once confident): fund with what you're prepared to trade live. With the default config, each entry is 0.35% of deposit and max exposure ≈ 15 positions-worth ≈ a few % — but fund only what you accept losing entirely.

## 4. BNB Agent SDK (20 min)

```bash
pip install "bnbagent[server,ipfs]"
# one-time on-chain identity (gas-free on testnet via MegaFuel):
cd agent && WALLET_PASSWORD=... PRIVATE_KEY=0x... python -m binacci.cli register
```

This mints an ERC-8004 identity and (via `binacci serve`) exposes APEX endpoints so other agents can *pay* for strategy specs — the post-hackathon business.

## 5. Run the stack locally

```bash
# Agent core
cd agent
pip install -e ".[dev,server]"
pytest                                   # 17 tests
python -m binacci.cli backtest --symbol BNB --timeframe 15m
python -m binacci.cli spec --symbol BNB --timeframe 4h --output spec.json
python -m binacci.cli serve            # API on :8000 (+ /apex if bnbagent installed)

# Dashboard
cd ../dashboard
npm install && npm run dev               # http://localhost:3000
```

## 6. Environment reference (Railway service variables / `agent/.env`)

```
# L1 — CoinMarketCap (data + macro gate + live loop)
BINACCI_CMC_API_KEY=...

# Engine
BINACCI_VENUE=paper            # paper -> pancake (mainnet swaps) when ready
BINACCI_DEPOSIT_USD=1000
BINACCI_USE_TESTNET=true       # NOTE: swaps unsupported on bsctestnet
BINACCI_WALLET_ADDRESS=0x...   # agent wallet (DoraHacks PnL replay address)
BINACCI_DATA_DIR=/data         # mount a Railway volume here for warm restarts

# L2 — Trust Wallet Agent Kit (entrypoint runs `twak init` + wallet create)
TWAK_ACCESS_ID=...             # from portal.trustwallet.com
TWAK_HMAC_SECRET=...
TWAK_WALLET_PASSWORD=...       # encrypts the local non-custodial wallet

# L3 — BNB AI Agent SDK (ERC-8004 identity + APEX paid jobs)
BINACCI_AUTO_REGISTER=true     # one-time on-chain registration at startup
WALLET_PASSWORD=...            # bnbagent keystore password
PRIVATE_KEY=0x...              # first run only; encrypted afterward
BINACCI_AGENT_CARD_URL=        # optional A2A agent card URL
```

## Risk notes (read before mainnet)

- The kill switch (30% aggregate drawdown) and 5-slot cap are enforced in code, but DEX slippage, MEV, and gas are not simulated by the paper venue beyond simple slippage. Run ≥3 days on testnet first.
- Trailing stops are emulated agent-side (DEXes have no native stops). If the agent process dies, stops die with it — run under a supervisor (systemd/pm2) with alerts.
- Never reuse the agent wallet elsewhere; cap funds to the live-window budget.
