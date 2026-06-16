# binacci-funding-carry

**Type:** strategy (perps, both-ways) · **Market:** on-chain perps · **Data:** CoinMarketCap spot + on-chain perp mark

## What it does
Derives perps **funding pressure** from the on-chain perp **mark** vs the **CoinMarketCap spot** quote (a basis proxy when a direct funding feed isn't on-plan), then **fades the crowded side**:

- Perp trades at a **premium** to spot → crowded longs are paying funding → **fade short**.
- Perp trades at a **discount** → crowded shorts → **fade long**.

It is perps-native and **uncorrelated** with Binacci's price-pattern strategies, so it diversifies the book. Entries are limits at the level (never market); the deterministic risk engine sizes and manages them like every other strategy.

## Signal
```
funding% = (perp_mark - spot) / spot * 100
state    = crowded_long  if funding% >  threshold   (fade short)
           crowded_short if funding% < -threshold   (fade long)
           neutral       otherwise
```
Threshold: `funding.min_abs_funding_pct` (default 0.05%). Strength scales with |funding|.

## Inputs / endpoint
- Live: `GET /funding` — per-symbol funding, fade classification, extremes.
- Idle when no perp mark is available (paper marks == spot → basis 0).

## Risk
Both-ways perp position; same 30% reserve, per-position hard stop, trailing, and 30% aggregate kill switch as the rest of the portfolio. Fee-aware entry gate applies.
