# binacci-basis-carry

**Type:** strategy (delta-neutral, uses both books) · **Data:** CoinMarketCap spot + on-chain perp mark

## What it does
When the perp trades at a **premium** to spot, the basis is a paid carry. Binacci opens both legs:
- **Short the rich perp** (the signal leg), and
- **Long equal-notional spot** (the hedge leg, opened automatically by the engine).

Price moves on the two legs cancel — the pair is **delta-neutral** — so it earns the **basis as it converges plus the funding** crowded longs pay, with no directional exposure. It is the only Binacci strategy that holds **both books at once on the same name**, and it's uncorrelated with everything else.

## Signal
```
basis% = (perp_mark - spot) / spot * 100
fire if basis% >= threshold   (premium only — the long-spot hedge requires a long leg)
legs:  SHORT perp  +  LONG spot (equal notional)  ->  delta-neutral
exit:  both legs close together (linked lifecycle)
```
Threshold: `funding.min_abs_funding_pct` (default 0.05%).

## Endpoint
`GET /basis` — premium carry candidates + any active pairs. Idle in paper (mark == spot).

## Risk
Delta-neutral by construction, so directional risk is minimal; residual risk is execution/funding-flip. Same reserve, hard stop, and 30% kill switch as the rest of the book; the hedge leg trades spot at 1×.
