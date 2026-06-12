"""Data layer — CMC Data API client, candle sources, synthetic generator.

CoinMarketCap is the data & signal layer (L1 of the sponsor stack):
* REST Data API for quotes, OHLCV, global metrics (totalCap, BTC.D, F&G).
* The CMC MCP (https://mcp.coinmarketcap.com/mcp) exposes the same signals
  to the conversational layer; the trading loop uses REST for determinism.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Protocol

import httpx
import pandas as pd

from .config import RuntimeConfig, Timeframe
from .macro import MacroSnapshot
from .models import Candle


# --------------------------------------------------------------------------
# Candle sources
# --------------------------------------------------------------------------

class CandleSource(Protocol):
    def history(self, symbol: str, tf: Timeframe, bars: int) -> list[Candle]: ...


@dataclass
class SyntheticSource:
    """Deterministic synthetic OHLCV for tests/backtests without API keys.

    Regime-switching geometric walk with mean-reverting reactions — rough
    but produces the swing structure (impulses + retracements) the strategy
    feeds on.
    """

    seed: int = 7
    base_price: dict[str, float] | None = None

    def history(self, symbol: str, tf: Timeframe, bars: int) -> list[Candle]:
        rng = random.Random(f"{self.seed}:{symbol}:{tf.value}")
        price = (self.base_price or {}).get(symbol, 100.0 + rng.random() * 400)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        step = timedelta(minutes=tf.minutes)
        start = now - step * bars
        out: list[Candle] = []
        trend = 0.0
        for i in range(bars):
            if rng.random() < 0.02:  # regime switch
                trend = rng.uniform(-0.0015, 0.0018)
            noise = rng.gauss(0, 0.004)
            drift = trend + noise
            o = price
            c = price * (1 + drift)
            hi = max(o, c) * (1 + abs(rng.gauss(0, 0.0018)))
            lo = min(o, c) * (1 - abs(rng.gauss(0, 0.0018)))
            vol = abs(rng.gauss(1.0, 0.45)) * 1000 * (1 + 8 * abs(drift))
            out.append(Candle(ts=start + step * i, open=o, high=hi, low=lo, close=c, volume=vol))
            price = c
        return out


@dataclass
class CSVSource:
    """Load candles from CSV files: ts,open,high,low,close,volume.
    File naming: {dir}/{symbol}_{tf}.csv"""

    directory: str

    def history(self, symbol: str, tf: Timeframe, bars: int) -> list[Candle]:
        path = f"{self.directory}/{symbol}_{tf.value}.csv"
        df = pd.read_csv(path, parse_dates=["ts"])
        df = df.tail(bars)
        return [
            Candle(ts=r.ts.to_pydatetime().replace(tzinfo=timezone.utc),
                   open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
            for r in df.itertuples()
        ]


# --------------------------------------------------------------------------
# CoinMarketCap client
# --------------------------------------------------------------------------

class CMCClient:
    """Thin client over the CMC Pro Data API.

    Endpoints used:
    * /v1/global-metrics/quotes/latest        -> macro gate inputs
    * /v2/cryptocurrency/quotes/latest        -> live quotes
    * /v2/cryptocurrency/ohlcv/historical     -> candles (plan-dependent)
    * /v3/fear-and-greed/latest               -> sentiment context
    """

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.cmc_base_url,
            headers={"X-CMC_PRO_API_KEY": cfg.cmc_api_key, "Accept": "application/json"},
            timeout=20.0,
        )
        self._macro_history: list[tuple[datetime, float, float, float]] = []

    def quotes(self, symbols: Iterable[str], convert: str = "USD") -> dict[str, float]:
        r = self._client.get(
            "/v2/cryptocurrency/quotes/latest",
            params={"symbol": ",".join(symbols), "convert": convert,
                    "skip_invalid": "true"},
        )
        r.raise_for_status()
        data = r.json()["data"]
        out: dict[str, float] = {}
        for sym, entries in data.items():
            if isinstance(entries, list):
                if not entries:
                    continue
                # ambiguous tickers return multiple coins — take the one
                # with the highest market cap (the canonical listing)
                e = max(entries, key=lambda x: (x.get("quote", {}).get(convert, {})
                                                .get("market_cap") or 0))
            else:
                e = entries
            try:
                out[sym] = float(e["quote"][convert]["price"])
            except (KeyError, TypeError):
                continue
        return out

    def global_metrics(self) -> dict:
        r = self._client.get("/v1/global-metrics/quotes/latest", params={"convert": "USD"})
        r.raise_for_status()
        return r.json()["data"]

    def fear_greed(self) -> Optional[int]:
        try:
            r = self._client.get("/v3/fear-and-greed/latest")
            r.raise_for_status()
            return int(r.json()["data"]["value"])
        except Exception:
            return None

    def macro_snapshot(self, lookback_hours: int = 24) -> MacroSnapshot:
        """Builds the macro gate input. Maintains an in-process history ring
        to compute lookback changes; for production persistence, snapshots
        are also written by the agent loop to disk."""
        g = self.global_metrics()
        q = g["quote"]["USD"]
        now = datetime.now(timezone.utc)
        total_cap = float(q["total_market_cap"])
        btc_d = float(g["btc_dominance"])
        usdt_d = float(g.get("stablecoin_dominance", g.get("usdt_dominance", 0.0)) or 0.0)
        if not usdt_d:
            # derive: stablecoin volume share fallback
            usdt_d = float(g.get("defi_dominance", 0.0) or 0.0)

        self._macro_history.append((now, total_cap, btc_d, usdt_d))
        cutoff = now - timedelta(hours=lookback_hours)
        self._macro_history = [x for x in self._macro_history if x[0] >= cutoff - timedelta(hours=2)]
        past = self._macro_history[0]

        def chg(cur: float, old: float) -> float:
            return (cur - old) / old * 100.0 if old else 0.0

        return MacroSnapshot(
            total_market_cap_usd=total_cap,
            btc_dominance_pct=btc_d,
            usdt_dominance_pct=usdt_d,
            total_cap_change_pct=chg(total_cap, past[1]),
            btc_dominance_change_pct=btc_d - past[2],
            usdt_dominance_change_pct=usdt_d - past[3],
            fear_greed=self.fear_greed(),
        )

    def close(self) -> None:
        self._client.close()


def resample_candles(candles: list[Candle], tf: Timeframe) -> list[Candle]:
    """Resample 1m-or-finer candles into a non-standard TF (13m, 21m, 89m...)."""
    if not candles:
        return []
    df = pd.DataFrame(
        {"ts": [c.ts for c in candles], "open": [c.open for c in candles],
         "high": [c.high for c in candles], "low": [c.low for c in candles],
         "close": [c.close for c in candles], "volume": [c.volume for c in candles]}
    ).set_index("ts")
    rule = f"{tf.minutes}min"
    agg = df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    return [Candle(ts=i.to_pydatetime(), open=r.open, high=r.high, low=r.low,
                   close=r.close, volume=r.volume) for i, r in agg.iterrows()]
