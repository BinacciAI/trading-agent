# Binacci Roadmap — next steps

Status: live on Railway (paper), 5-strategy portfolio over 50+ BNB markets,
Track-2 skill family, warm-restart persistence, dashboard live.

## Now (pre-submission, by Jun 21)
1. **Activate ERC-8004 identity** — set `BINACCI_AUTO_REGISTER=true` + a funded
   testnet key so the agent mints its on-chain identity (gas-free on
   bsc-testnet via MegaFuel). Surface it on the dashboard via `/chain`.
2. **Dashboard Chain panel** — render `/chain` (SDK installed, APEX mounted,
   ERC-8004 agentId, network) so the BNB SDK use is visible to judges.
3. **Real-data backtests** — `BINACCI_BACKTEST_SOURCE=checkpoint` uses the
   agent's own accumulated CMC chart data (the plan lacks historical OHLCV).
   Let it accumulate; the "All markets" view then runs on real data.
4. **Mainnet dust swap rehearsal** — one tiny PancakeSwap swap via TWAK to
   prove the execution path end-to-end before the live window.
5. **Demo video** — brains/hands split, gate audit, live dashboard, a Track-2
   spec, an APEX job.

## Live window (Jun 22–28)
- Run **Balanced** risk mode; monitor the kill switch + per-strategy P/L.
- Keep deploys frozen (watchPatterns already prevents non-source restarts;
  use a release branch for any hotfix).

## Near-term product
6. **Macro regime classifier** skill — gate the whole portfolio by
   risk-on/chop/risk-off (best-use-of-CMC-data prize).
7. **Narrative/sector rotation** skill — tilt the universe toward hot CMC
   narratives.
8. **Smart order router** (TWAK) — slippage caps, fill splitting on real swaps.
9. **APEX monetization live** — sell strategy specs as escrowed ERC-8183 jobs;
   wire x402 pay-per-call.
10. **Deeper history** — either a CMC OHLCV plan add-on, or grow the 1m
    checkpoint window (BINACCI_MAX_1M_BARS) for longer backtests.

## Bigger bets (post-hackathon)
- BSC perps venue (shorts) via the BNB SDK primitives.
- Portfolio-level position sizing across strategies (shared-book backtest).
- Auto-promote strategies paper→live once they clear backtest + paper gates.
- Multi-tenant: users bring a wallet + risk mode; Binacci runs their book.
