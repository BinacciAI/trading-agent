# Binacci — Real-Money Go-Live Runbook

Trading runs on the hardened venue path: **preflight → fill reconciliation → rollback on venue
failure → auto-halt on desync**, with the **sentinel** (de-peg/flash-crash) and **30% kill switch**
above it, and a **go-live ramp cap** that keeps the first orders dust-sized.

## Sequence
1. **Wallet** — a dedicated BSC wallet via Trust Wallet Agent Kit. Set `TWAK_ACCESS_ID`,
   `TWAK_HMAC_SECRET`, `TWAK_WALLET_PASSWORD`, and `BINACCI_WALLET_ADDRESS`.
2. **Fund** — USDT (trading capital) + ~$10–20 **BNB for gas**.
3. **Ramp cap** — `BINACCI_GOLIVE_MAX_USD=25` so every first order caps exposure at $25 (notional =
   margin × leverage), regardless of the leverage tier.
4. **Flip** — `BINACCI_VENUE=perps` (perps are fee-advantaged vs spot) and `BINACCI_USE_TESTNET=false`;
   redeploy.
5. **Preflight** — `POST /venue/preflight` (or the Go-Live page button). Resolve any failure before trading.
6. **Verify** — confirm the first real fills + tx hashes resolve on BscScan; watch `/sentinel`, `/venue`,
   Execution Logs.
7. **Scale** — raise `BINACCI_GOLIVE_MAX_USD` once the fill/fee/reconcile loop is proven.

## Safety
- **Operator halt** (Settings) blocks new opens; existing positions keep being managed/closed.
- **Sentinel** halts on stablecoin de-peg / flash move / broad crash; clear via `POST /venue/resume`.
- **Reconcile/rollback** keep books == chain; a desync auto-halts.
- **Fee-aware gate** auto-on for live — never opens a setup that can't clear fees+gas.
- **30% aggregate-drawdown kill switch** force-flattens.

## Caution
Real funds at leverage = real loss risk. Keep the ramp cap on until on-chain fills are verified.
The `$1000` config (10 slots, 25× perps, wide trailing, fee gate) is net-of-fee positive in sim but
its real edge needs live confirmation — start dust-sized.
