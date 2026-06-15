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
        """Market-realistic OHLCV: persistent trends (momentum) with
        pullbacks toward a slow anchor (mean reversion), so the structure the
        strategies hunt — impulses, retracements, squeezes, trend pullbacks —
        actually exists. A pure random walk has no edge to extract; this makes
        the verification backtest meaningful rather than coin-flip noise.
        """
        rng = random.Random(f"{self.seed}:{symbol}:{tf.value}")
        price = (self.base_price or {}).get(symbol, 100.0 + rng.random() * 400)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        step = timedelta(minutes=tf.minutes)
        start = now - step * bars
        out: list[Candle] = []
        trend = 0.0          # persistent drift (momentum)
        anchor = price       # slow mean (reversion target)
        vol = 0.0030         # base per-bar volatility
        for i in range(bars):
            # momentum: trend persists (autocorrelation) with occasional shocks
            if rng.random() < 0.05:
                trend += rng.gauss(0, 0.0016)
            trend *= 0.93
            trend = max(-0.006, min(0.006, trend))
            # mean reversion: pull back toward the slow anchor (makes pullbacks)
            rev = -0.035 * (price / anchor - 1.0)
            # volatility clusters mildly
            vol = max(0.0014, min(0.0065, vol * 0.96 + abs(rng.gauss(0, 0.0009)) * 0.04 + 0.0001))
            noise = rng.gauss(0, vol * 0.55)
            drift = trend + rev + noise
            o = price
            c = price * (1 + drift)
            wick = abs(rng.gauss(0, vol * 0.5))
            hi = max(o, c) * (1 + wick)
            lo = min(o, c) * (1 - wick)
            bar_vol = abs(rng.gauss(1.0, 0.4)) * 1000 * (1 + 9 * abs(drift))
            out.append(Candle(ts=start + step * i, open=o, high=hi, low=lo, close=c, volume=bar_vol))
            price = c
            anchor = anchor * 0.992 + price * 0.008
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
        """Latest price per symbol. One batched call (1 credit / 100 symbols)."""
        return {s: q["price"] for s, q in self.quotes_full(symbols, convert).items()}

    def quotes_full(self, symbols: Iterable[str], convert: str = "USD") -> dict[str, dict]:
        """Latest price PLUS the fields the live loop needs to build a real
        volume signal: 24h volume and 1h/24h percent change. Same single
        batched request as :meth:`quotes` — no extra credits."""
        syms = list(symbols)
        if not syms:
            return {}
        r = self._client.get(
            "/v2/cryptocurrency/quotes/latest",
            params={"symbol": ",".join(syms), "convert": convert,
                    "skip_invalid": "true"},
        )
        r.raise_for_status()
        data = r.json()["data"]
        out: dict[str, dict] = {}
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
            q = (e.get("quote") or {}).get(convert) or {}
            try:
                price = float(q["price"])
            except (KeyError, TypeError):
                continue
            out[sym] = {
                "price": price,
                "volume_24h": float(q.get("volume_24h") or 0.0),
                "percent_change_1h": float(q.get("percent_change_1h") or 0.0),
                "percent_change_24h": float(q.get("percent_change_24h") or 0.0),
            }
        return out

    def ohlcv_historical(self, symbol: str, tf: Timeframe, bars: int,
                         convert: str = "USD") -> list[Candle]:
        """Best-effort historical OHLCV for warmup. Returns [] if the plan
        does not include the OHLCV endpoint (the loop then warms from live
        ticks instead). Uses the closest standard interval CMC supports and
        resamples to the requested non-standard timeframe if needed."""
        interval, std_minutes = _closest_cmc_interval(tf.minutes)
        count = min(max(int(bars * tf.minutes / std_minutes) + 5, bars), 10000)
        try:
            r = self._client.get(
                "/v2/cryptocurrency/ohlcv/historical",
                params={"symbol": symbol, "convert": convert,
                        "interval": interval, "count": count},
            )
            r.raise_for_status()
        except Exception:
            return []
        try:
            payload = r.json()["data"]
            quotes = payload["quotes"] if isinstance(payload, dict) else payload[0]["quotes"]
        except (KeyError, IndexError, TypeError):
            return []
        candles: list[Candle] = []
        for row in quotes:
            o = row.get("quote", {}).get(convert, {})
            try:
                ts = datetime.fromisoformat(row["time_open"].replace("Z", "+00:00"))
                candles.append(Candle(ts=ts, open=float(o["open"]), high=float(o["high"]),
                                      low=float(o["low"]), close=float(o["close"]),
                                      volume=float(o.get("volume") or 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
        if std_minutes != tf.minutes and candles:
            candles = resample_candles(candles, tf)
        return candles[-bars:]

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

    def macro_snapshot(self, lookback_hours: int = 24, fetch_fear_greed: bool = True,
                       cached_fear_greed: Optional[int] = None) -> MacroSnapshot:
        """Builds the macro gate input. Maintains an in-process history ring
        to compute lookback changes; for production persistence, snapshots
        are also written by the agent loop to disk.

        F&G is on its own cadence (it barely moves intraday and costs a
        credit), so the caller can skip the call and inject a cached value."""
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

        fg = self.fear_greed() if fetch_fear_greed else cached_fear_greed
        return MacroSnapshot(
            total_market_cap_usd=total_cap,
            btc_dominance_pct=btc_d,
            usdt_dominance_pct=usdt_d,
            total_cap_change_pct=chg(total_cap, past[1]),
            btc_dominance_change_pct=btc_d - past[2],
            usdt_dominance_change_pct=usdt_d - past[3],
            fear_greed=fg,
        )

    def close(self) -> None:
        self._client.close()


#: CMC-supported OHLCV interval strings -> minutes.
_CMC_INTERVALS: dict[str, int] = {
    "1m": 1, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "45m": 45,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
    "1d": 1440, "3d": 4320, "7d": 10080,
}


def _closest_cmc_interval(minutes: int) -> tuple[str, int]:
    """Pick a CMC OHLCV interval for a (possibly non-standard) timeframe.

    Exact match if CMC supports it; otherwise the largest supported interval
    that divides the target (so it resamples cleanly); else fall back to 1m.
    """
    for name, m in _CMC_INTERVALS.items():
        if m == minutes:
            return name, m
    best = ("1m", 1)
    for name, m in _CMC_INTERVALS.items():
        if minutes % m == 0 and m > best[1]:
            best = (name, m)
    return best


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
