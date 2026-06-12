"""Live loop — feeds the engine with real market data 24/7.

Design constraints:
* CMC free tier has no deep OHLCV history -> we BUILD candles by polling
  quotes (one batched call for all symbols) and aggregating into 1m bars,
  then resampling into entry timeframes. Higher TFs warm up over time;
  gates stay closed until enough bars exist (fail closed, as always).
* Macro gate refreshes from CMC global metrics every 5 minutes.
* State is in-process; candle history is checkpointed to disk so restarts
  resume warm (mount a Railway volume at BINACCI_DATA_DIR for persistence).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import RuntimeConfig, StrategyConfig, Timeframe
from .data import CMCClient
from .execution import ExecutionEngine
from .indicators import to_dataframe
from .macro import MacroSnapshot
from .models import Candle
from .orchestrator import Orchestrator
from .venues import Venue, make_venue

log = logging.getLogger(__name__)

#: TFs the live loop trades — achievable from live 1m accumulation.
DEFAULT_LIVE_TFS = [Timeframe.M3, Timeframe.M10, Timeframe.M15, Timeframe.M30]
MAX_1M_BARS = 2880  # 48h of 1m bars per symbol


@dataclass
class MinuteBuilder:
    """Aggregates polled quotes into 1-minute candles."""

    bars: deque = field(default_factory=lambda: deque(maxlen=MAX_1M_BARS))
    cur_minute: Optional[datetime] = None
    o: float = 0.0
    h: float = 0.0
    l: float = 0.0
    c: float = 0.0
    ticks: int = 0

    def add(self, ts: datetime, price: float) -> Optional[Candle]:
        """Add a tick; returns the COMPLETED candle when a minute rolls."""
        minute = ts.replace(second=0, microsecond=0)
        done: Optional[Candle] = None
        if self.cur_minute is None:
            self.cur_minute = minute
            self.o = self.h = self.l = self.c = price
            self.ticks = 1
            return None
        if minute > self.cur_minute:
            done = Candle(ts=self.cur_minute, open=self.o, high=self.h,
                          low=self.l, close=self.c, volume=float(self.ticks))
            self.bars.append(done)
            self.cur_minute = minute
            self.o = self.h = self.l = self.c = price
            self.ticks = 1
            return done
        self.h = max(self.h, price)
        self.l = min(self.l, price)
        self.c = price
        self.ticks += 1
        return None

    def resample(self, tf: Timeframe) -> list[Candle]:
        """1m bars -> tf bars (completed only)."""
        out: list[Candle] = []
        bucket: list[Candle] = []
        minutes = tf.minutes
        for b in self.bars:
            epoch_min = int(b.ts.timestamp() // 60)
            if bucket and epoch_min // minutes != int(bucket[0].ts.timestamp() // 60) // minutes:
                out.append(_merge(bucket))
                bucket = []
            bucket.append(b)
        # bucket in progress is NOT emitted (incomplete bar)
        return out


def _merge(bars: list[Candle]) -> Candle:
    return Candle(
        ts=bars[0].ts,
        open=bars[0].open,
        high=max(b.high for b in bars),
        low=min(b.low for b in bars),
        close=bars[-1].close,
        volume=sum(b.volume for b in bars),
    )


class LiveLoop:
    def __init__(self, scfg: StrategyConfig, rcfg: RuntimeConfig,
                 engine: ExecutionEngine, orch: Orchestrator):
        self.scfg = scfg
        self.rcfg = rcfg
        self.engine = engine
        self.orch = orch
        self.builders: dict[str, MinuteBuilder] = {s: MinuteBuilder() for s in scfg.symbols}
        self.prices: dict[str, float] = {}
        self.live_tfs = DEFAULT_LIVE_TFS
        self.macro: Optional[MacroSnapshot] = None
        self.cmc: Optional[CMCClient] = None
        self.started_at: Optional[datetime] = None
        self.last_poll: Optional[datetime] = None
        self.last_macro: Optional[datetime] = None
        self.polls = 0
        self.errors = 0
        self.last_error = ""
        self._emitted: dict[tuple[str, str], datetime] = {}
        self.data_dir = Path(os.environ.get("BINACCI_DATA_DIR", "/tmp/binacci-data"))
        # the orchestrator's macro provider reads our cache
        self.orch.macro_provider = lambda: self.macro
        # venue execution: engine decides, venue mirrors on-chain
        self.venue: Venue = make_venue(rcfg)
        self.venue_log: list[dict] = []
        #: Liquidity-verified symbols (None until verification completes).
        #: Unverified symbols are analyzed but never executed on-chain.
        self.verified: Optional[dict[str, dict]] = None
        if rcfg.venue != "paper":
            self.orch.on_open = self._venue_open
            self.orch.on_close = self._venue_close

    # ---------------- venue hooks ----------------

    def _venue_open(self, pos) -> None:
        if self.verified is not None and pos.symbol not in self.verified:
            self.venue_log.append({
                "ts": datetime.now(timezone.utc).isoformat(), "action": "open",
                "symbol": pos.symbol, "ok": False,
                "detail": "blocked: symbol not liquidity-verified",
            })
            return
        res = self.venue.place_limit(pos.symbol, pos.side, pos.avg_entry, pos.notional_usd)
        self.venue_log.append({
            "ts": datetime.now(timezone.utc).isoformat(), "action": "open",
            "symbol": pos.symbol, "notional_usd": round(pos.notional_usd, 2),
            "ok": res.ok, "tx": res.tx_or_id, "detail": res.detail,
        })
        if res.ok and res.fill_price:
            pos.meta["venue_fill_price"] = res.fill_price
            pos.meta["venue_tx"] = res.tx_or_id
        if not res.ok:
            log.error("venue open failed for %s: %s", pos.symbol, res.detail)

    def _venue_close(self, trade) -> None:
        pos = trade.position
        res = self.venue.market_close(pos.symbol, pos.side, abs(pos.fills[-1].notional_usd))
        self.venue_log.append({
            "ts": datetime.now(timezone.utc).isoformat(), "action": "close",
            "symbol": pos.symbol, "reason": trade.reason,
            "ok": res.ok, "tx": res.tx_or_id, "detail": res.detail,
        })
        if not res.ok:
            log.error("venue close failed for %s: %s", pos.symbol, res.detail)

    # ---------------- status ----------------

    @property
    def running(self) -> bool:
        return self.started_at is not None

    def warmup_info(self) -> dict:
        bars = {s: len(b.bars) for s, b in self.builders.items()}
        need = max(self.scfg.sims.extrema_window * 2 + 2, 60)
        return {
            "one_minute_bars": bars,
            "tradable_tfs": [
                tf.value for tf in self.live_tfs
                if min(bars.values() or [0]) >= need * tf.minutes
            ],
        }

    def status(self) -> dict:
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_poll": self.last_poll.isoformat() if self.last_poll else None,
            "polls": self.polls,
            "errors": self.errors,
            "last_error": self.last_error,
            "macro_fresh": bool(self.macro),
            "symbols": self.scfg.symbols,
            "warmup": self.warmup_info(),
            "venue": self.rcfg.venue,
            "venue_log_tail": self.venue_log[-5:],
            "universe": {
                "candidates": len(self.scfg.symbols),
                "verified": sorted(self.verified) if self.verified is not None else None,
                "verified_count": len(self.verified) if self.verified is not None else None,
            },
        }

    # ---------------- persistence ----------------

    def _checkpoint(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for s, b in self.builders.items():
                rows = [[c.ts.isoformat(), c.open, c.high, c.low, c.close, c.volume]
                        for c in b.bars]
                (self.data_dir / f"{s}_1m.json").write_text(json.dumps(rows))
        except Exception:  # pragma: no cover
            log.exception("checkpoint failed")

    def _restore(self) -> None:
        for s, b in self.builders.items():
            p = self.data_dir / f"{s}_1m.json"
            if not p.exists():
                continue
            try:
                for ts, o, h, l, c, v in json.loads(p.read_text()):
                    b.bars.append(Candle(ts=datetime.fromisoformat(ts),
                                         open=o, high=h, low=l, close=c, volume=v))
                log.info("restored %d 1m bars for %s", len(b.bars), s)
            except Exception:  # pragma: no cover
                log.exception("restore failed for %s", s)

    # ---------------- universe verification ----------------

    def _should_verify(self) -> bool:
        mode = self.rcfg.verify_liquidity.lower()
        if mode == "false":
            return False
        from .venues import TwakCLI

        if mode == "true":
            return True
        return TwakCLI().installed  # auto

    def _verify_universe(self) -> None:
        """Self-source the tradable universe: $1 test-quote every candidate
        through TWAK on BSC; keep symbols that resolve with price impact
        under the configured ceiling. Cached to disk for 24h."""
        from .venues import TwakCLI

        cache = self.data_dir / "universe.json"
        try:
            if cache.exists():
                data = json.loads(cache.read_text())
                age = datetime.now(timezone.utc) - datetime.fromisoformat(data["ts"])
                if age < timedelta(hours=24):
                    self.verified = data["verified"]
                    log.info("universe from cache: %d verified", len(self.verified))
                    return
        except Exception:
            log.exception("universe cache read failed")

        twak = TwakCLI(timeout_s=45)
        verified: dict[str, dict] = {}
        for sym in self.scfg.symbols:
            res = twak.quote_swap("USDT", sym, usd=1.0, chain="bsc")
            if res.get("error"):
                log.info("universe drop %s: %s", sym, str(res.get("error"))[:120])
                continue
            try:
                impact = abs(float(res.get("priceImpact") or 0.0))
            except (TypeError, ValueError):
                impact = 0.0
            if impact > self.rcfg.max_price_impact_pct:
                log.info("universe drop %s: price impact %.2f%%", sym, impact)
                continue
            verified[sym] = {"priceImpact": impact, "provider": res.get("provider", "")}
        self.verified = verified
        log.info("universe verified: %d/%d tradable", len(verified), len(self.scfg.symbols))
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(
                {"ts": datetime.now(timezone.utc).isoformat(), "verified": verified}))
        except Exception:
            log.exception("universe cache write failed")

    # ---------------- core loop ----------------

    async def run(self) -> None:
        if not self.rcfg.cmc_api_key:
            log.warning("BINACCI_CMC_API_KEY not set — live loop idle")
            return
        self.cmc = CMCClient(self.rcfg)
        self._restore()
        self.started_at = datetime.now(timezone.utc)
        log.info("live loop started: %d candidates on %s", len(self.scfg.symbols),
                 [tf.value for tf in self.live_tfs])
        if self._should_verify():
            asyncio.get_event_loop().run_in_executor(None, self._verify_universe)
        poll_s = max(int(self.rcfg.poll_seconds), 10)
        checkpoint_every = 30  # polls
        while True:
            try:
                await asyncio.to_thread(self._poll_once)
            except Exception as e:
                self.errors += 1
                self.last_error = f"{type(e).__name__}: {e}"
                log.exception("poll failed")
            if self.polls % checkpoint_every == 0 and self.polls:
                await asyncio.to_thread(self._checkpoint)
            await asyncio.sleep(poll_s)

    def _poll_once(self) -> None:
        assert self.cmc is not None
        now = datetime.now(timezone.utc)

        # 1) quotes -> ticks -> 1m candles
        quotes = self.cmc.quotes(self.scfg.symbols)
        self.prices.update(quotes)
        completed: dict[str, Candle] = {}
        for sym, price in quotes.items():
            done = self.builders[sym].add(now, price)
            if done:
                completed[sym] = done
        self.last_poll = now
        self.polls += 1

        # 2) macro refresh every 5 min
        if self.last_macro is None or (now - self.last_macro) > timedelta(minutes=5):
            try:
                self.macro = self.cmc.macro_snapshot(self.scfg.macro.lookback_hours)
                self.last_macro = now
            except Exception:
                log.exception("macro refresh failed — gate fails closed")
                self.macro = None

        # 3) on each completed 1m bar, check TF boundaries
        for sym in completed:
            builder = self.builders[sym]
            for tf in self.live_tfs:
                bars = builder.resample(tf)
                need = self.scfg.sims.extrema_window * 2 + 4
                if len(bars) < need:
                    continue
                newest = bars[-1]
                key = (sym, tf.value)
                if self._emitted.get(key) == newest.ts:
                    continue  # no new completed bar on this TF
                self._emitted[key] = newest.ts
                df = to_dataframe(bars[-400:])
                self.orch.update_references(sym, tf, df)
                self.orch.evaluate(sym, tf, df, ts=newest.ts)
                self.orch.on_candle(sym, tf, newest, dict(self.prices))
