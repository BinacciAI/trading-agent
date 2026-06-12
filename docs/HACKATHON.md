# Hackathon Plan — 10 days to submission

**Deadline: June 21, 12:00 UTC. Live trading window: June 22–28. Today: June 11.**

## Day-by-day

| Date | Goal |
|---|---|
| Jun 11 | ✅ Core engine + backtester + skill + API + dashboard built and tested. Register on DoraHacks, get CMC key (SETUP.md §1–2). |
| Jun 12 | TWAK installed, reference agent running on BSC testnet. Probe actual TWAK REST/MCP surface; align `venues.py` endpoints to it. |
| Jun 13 | Real data in: CMC OHLCV → CSVSource; rerun backtests on real BNB/BTC/ETH/CAKE history across 15m/1h/4h. Tune `level_tolerance_pct` and `volume_min_ratio` against real microstructure. |
| Jun 14 | Live loop daemon: scheduler polling CMC, evaluating all symbols × TFs, executing on testnet PancakeSwap through TWAK. Supervisor + alerting. |
| Jun 15 | ERC-8004 registration on testnet; APEX server live; end-to-end paid spec job demo (client funds job → agent delivers spec → settlement). |
| Jun 16 | Perps adapter: wire to BSC perps via TWAK/BNB SDK if surface is ready; otherwise document as roadmap and keep spot. 72-hour testnet soak starts. |
| Jun 17–18 | Soak monitoring. Track 2 polish: spec on real data, manifest, x402 pricing. Dashboard demo polish. |
| Jun 19 | Decide mainnet capital. Fund wallet. Switch `BINACCI_USE_TESTNET=false`, `BINACCI_VENUE=pancake`. Dry-run with one tiny manual-confirmed trade. |
| Jun 20 | Record demo video (≤3 min): the 5-gate trace refusing bad entries, then a clean entry → trailing SL → green close. Write DoraHacks submission (both tracks). |
| Jun 21 AM | Submit before 12:00 UTC. Freeze code. |
| Jun 22–28 | Unattended live window. Daily health checks only — no strategy edits. |

## Submission checklist (both tracks)

- [ ] DoraHacks project page: Track 1 (agent) + Track 2 (skill) entries
- [ ] Public repo (framework open; production parameters + CMD private in strategy-core)
- [ ] Demo video ≤3 min
- [ ] Track 1: live wallet address for PnL replay; agent running unattended
- [ ] Track 2: `spec.json` sample + manifest + backtest reproducibility instructions
- [ ] Special prize callouts in the README: CMC data usage map, TWAK usage, BNB SDK usage (all three are stackable $2K prizes)

## Win conditions

1. **Track 1 judging is live PnL replay.** The strategy's profile — many small green closes, trailing stops at ~breakeven, hard caps — is built to look excellent on a 7-day replay where degen agents blow up. Conservative by risk, active by trade count.
2. **Stack all three sponsors visibly.** CMC (macro gate + technicals), TWAK (self-custody autonomous signing), BNB SDK (ERC-8004 + APEX). The README maps each — judges shouldn't have to hunt.
3. **Differentiation narrative:** "AI is only an executor." Every entry has a 5-gate audit trace; every spec is replayable. Institutional discipline vs. prompt-trading.

## Open risks

| Risk | Mitigation |
|---|---|
| TWAK API surface differs from assumed REST layout | Day-2 probe; `venues.py` isolates all chain calls |
| CMC free tier lacks OHLCV history | Hobbyist plan $29/mo; or bootstrap candles from DEX data tools |
| Perps integration not ready in time | Spot-only submission is fully valid; perps = roadmap slide |
| Live window process crash kills agent-side stops | Supervisor + restart-rescan (engine state persisted), Telegram alert |
| Thin synthetic-data tuning vs real markets | Day-3 real-data backtests before any param freeze |
