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

#: TFs the live loop trades — achievable from live 1m accumulation. Widened
#: so more strategies can fire sooner (each TF is an independent stream).
DEFAULT_LIVE_TFS = [Timeframe.M3, Timeframe.M10, Timeframe.M13,
                    Timeframe.M15, Timeframe.M21, Timeframe.M30]
#: 1m-bar retention per symbol (also the depth available to checkpoint
#: backtests). Env-tunable; default 3 days. Persisted to BINACCI_DATA_DIR.
MAX_1M_BARS = int(os.environ.get("BINACCI_MAX_1M_BARS", "4320"))


@dataclass
class MinuteBuilder:
    """Aggregates polled quotes into 1-minute candles.

    Candle *volume* is the real traded volume in the minute, derived from the
    delta of CMC's reported rolling 24h volume between polls. This matters:
    the old build used the poll tick-count as "volume", which is roughly
    constant, so the volume-ratio entry filter could almost never fire — a
    silent, permanent block on every volume-gated strategy. Using the 24h
    volume delta makes the volume filter a real signal again.
    """

    bars: deque = field(default_factory=lambda: deque(maxlen=MAX_1M_BARS))
    cur_minute: Optional[datetime] = None
    o: float = 0.0
    h: float = 0.0
    l: float = 0.0
    c: float = 0.0
    ticks: int = 0
    vol: float = 0.0
    _prev_vol24h: Optional[float] = None

    def add(self, ts: datetime, price: float,
            vol24h: Optional[float] = None) -> Optional[Candle]:
        """Add a tick; returns the COMPLETED candle when a minute rolls."""
        minute = ts.replace(second=0, microsecond=0)
        inc = self._volume_increment(vol24h)
        if self.cur_minute is None:
            self.cur_minute = minute
            self.o = self.h = self.l = self.c = price
            self.ticks = 1
            self.vol = inc
            return None
        if minute > self.cur_minute:
            done = Candle(ts=self.cur_minute, open=self.o, high=self.h,
                          low=self.l, close=self.c,
                          volume=self.vol if self.vol > 0 else float(self.ticks))
            self.bars.append(done)
            self.cur_minute = minute
            self.o = self.h = self.l = self.c = price
            self.ticks = 1
            self.vol = inc
            return done
        self.h = max(self.h, price)
        self.l = min(self.l, price)
        self.c = price
        self.ticks += 1
        self.vol += inc
        return None

    def _volume_increment(self, vol24h: Optional[float]) -> float:
        """Traded volume since the last tick ≈ positive change in the rolling
        24h volume. The window can tick down as old trades age out, so we
        floor negatives at 0 and let tick-count be the fallback when no 24h
        volume is supplied."""
        if vol24h is None:
            return 0.0
        prev = self._prev_vol24h
        self._prev_vol24h = vol24h
        if prev is None:
            return 0.0
        delta = vol24h - prev
        return delta if delta > 0 else 0.0

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
        self.last_fg: Optional[datetime] = None
        self.fear_greed_value: Optional[int] = None
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
        chain_sym = self.scfg.chain_symbol(pos.symbol)
        res = self.venue.place_limit(chain_sym, pos.side, pos.avg_entry, pos.notional_usd)
        self.venue_log.append({
            "ts": datetime.now(timezone.utc).isoformat(), "action": "open",
            "symbol": pos.symbol, "chain_symbol": chain_sym,
            "strategy": pos.meta.get("strategy", "reaction"),
            "notional_usd": round(pos.notional_usd, 2),
            "ok": res.ok, "tx": res.tx_or_id, "detail": res.detail,
        })
        if res.ok and res.fill_price:
            pos.meta["venue_fill_price"] = res.fill_price
            pos.meta["venue_tx"] = res.tx_or_id
        if not res.ok:
            log.error("venue open failed for %s: %s", pos.symbol, res.detail)

    def _venue_close(self, trade) -> None:
        pos = trade.position
        res = self.venue.market_close(self.scfg.chain_symbol(pos.symbol), pos.side,
                                      abs(pos.fills[-1].notional_usd))
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

    def poll_symbols(self) -> list[str]:
        """Symbols to actually request quotes for = the ANALYSIS universe.

        In paper mode there is no on-chain execution, so liquidity
        verification must NOT narrow what we analyze — we watch all candidates
        (that's how the agent runs 50+ markets). Only on a real execution
        venue do we restrict polling to liquidity-verified symbols, and only
        to save CMC credits on coins that could never fill on-chain."""
        if self.rcfg.venue == "paper":
            return list(self.scfg.symbols)
        if (self.rcfg.poll_only_verified and self.verified is not None
                and len(self.verified) > 0):
            return [s for s in self.scfg.symbols if s in self.verified]
        return list(self.scfg.symbols)

    def credit_estimate(self) -> dict:
        """Rough CMC credit burn so the operator can see the cost knob.
        quotes = 1 credit per poll (one batched call); macro = 1 per refresh;
        F&G = 1 per refresh (0 if disabled)."""
        day = 86400
        q = day / max(self.rcfg.poll_seconds, 10)
        m = day / max(self.rcfg.macro_refresh_seconds, 60)
        fg = (day / self.rcfg.fear_greed_refresh_seconds) if self.rcfg.fear_greed_refresh_seconds else 0
        per_day = q + m + fg
        return {
            "per_day": round(per_day),
            "per_month": round(per_day * 30),
            "breakdown": {"quotes": round(q), "macro": round(m), "fear_greed": round(fg)},
            "poll_seconds": self.rcfg.poll_seconds,
            "polled_symbols": len(self.poll_symbols()),
        }

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
            "strategies": [s.name for s in self.orch.strategies],
            "risk_mode": self.scfg.risk_mode.value,
            "risk": self.scfg.risk_summary(),
            "markets": len(self.poll_symbols()),
            "universe": {
                "candidates": len(self.scfg.symbols),
                "markets": len(self.poll_symbols()),
                "polled": len(self.poll_symbols()),
                "verified": sorted(self.verified) if self.verified is not None else None,
                "verified_count": len(self.verified) if self.verified is not None else None,
            },
            "credits": self.credit_estimate(),
        }

    # ---------------- persistence ----------------

    def _checkpoint(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for s, b in self.builders.items():
                rows = [[c.ts.isoformat(), c.open, c.high, c.low, c.close, c.volume]
                        for c in b.bars]
                (self.data_dir / f"{s}_1m.json").write_text(json.dumps(rows))
            from .persistence import dump_state
            dump_state(self.engine, self.orch, self.data_dir / "state.json")
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
        try:
            from .persistence import load_state
            if load_state(self.engine, self.orch, self.data_dir / "state.json"):
                log.info("warm restart: engine state restored from volume")
        except Exception:  # pragma: no cover
            log.exception("engine state restore failed")

    # ---------------- universe verification ----------------

    def _should_verify(self) -> bool:
        mode = self.rcfg.verify_liquidity.lower()
        if mode == "false":
            return False
        # Paper mode never executes on-chain, so there's nothing to gate on
        # liquidity — skip verification entirely (and analyze every symbol).
        if self.rcfg.venue == "paper" and mode == "auto":
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
            res = twak.quote_swap("USDT", self.scfg.chain_symbol(sym), usd=1.0, chain="bsc")
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

    # ---------------- warmup ----------------

    def _backfill_warmup(self) -> None:
        """Best-effort: pull historical OHLCV from CMC so every symbol/TF has
        references on boot instead of warming up over many hours from live
        ticks. Silently no-ops per symbol if the plan lacks the OHLCV
        endpoint — the live accumulation path still works."""
        if not self.rcfg.warmup_backfill or self.cmc is None:
            return
        bars = self.rcfg.warmup_backfill_bars
        ok = 0
        for sym in self.scfg.symbols:
            for tf in self.live_tfs:
                try:
                    hist = self.cmc.ohlcv_historical(sym, tf, bars)
                except Exception:
                    hist = []
                if len(hist) < self.scfg.sims.extrema_window * 2 + 4:
                    continue
                df = to_dataframe(hist)
                self.orch.cold_start(sym, tf, df)
                self.orch.update_references(sym, tf, df)
                ok += 1
        log.info("warmup backfill seeded %d (symbol,tf) reference sets", ok)

    def _min_bars_needed(self) -> int:
        """Fewest bars any active strategy needs — the live loop evaluates as
        soon as that's met, and each strategy self-gates on its own minimum."""
        mins = [s.min_bars for s in self.orch.strategies] or [28]
        return max(20, min(mins))

    # ---------------- core loop ----------------

    async def run(self) -> None:
        if not self.rcfg.cmc_api_key:
            log.warning("BINACCI_CMC_API_KEY not set — live loop idle")
            return
        self.cmc = CMCClient(self.rcfg)
        self._restore()
        self.started_at = datetime.now(timezone.utc)
        log.info("live loop started: %d candidates, %d strategies on %s",
                 len(self.scfg.symbols), len(self.orch.strategies),
                 [tf.value for tf in self.live_tfs])
        if self._should_verify():
            asyncio.get_event_loop().run_in_executor(None, self._verify_universe)
        # warmup backfill off the event loop (network-heavy, best-effort)
        asyncio.get_event_loop().run_in_executor(None, self._backfill_warmup)
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

        # 1) quotes -> ticks -> 1m candles (volume = real 24h-volume delta).
        #    Poll only tradable symbols once verified -> no wasted credits.
        full = self.cmc.quotes_full(self.poll_symbols())
        completed: dict[str, Candle] = {}
        for sym, q in full.items():
            self.prices[sym] = q["price"]
            done = self.builders[sym].add(now, q["price"], vol24h=q.get("volume_24h"))
            if done:
                completed[sym] = done
        self.last_poll = now
        self.polls += 1

        # 2) macro refresh on its own (credit-aware) cadence; F&G even rarer
        macro_due = (self.last_macro is None
                     or (now - self.last_macro).total_seconds() >= self.rcfg.macro_refresh_seconds)
        if macro_due:
            fg_secs = self.rcfg.fear_greed_refresh_seconds
            fg_due = bool(fg_secs) and (self.last_fg is None
                        or (now - self.last_fg).total_seconds() >= fg_secs)
            try:
                self.macro = self.cmc.macro_snapshot(
                    self.scfg.macro.lookback_hours,
                    fetch_fear_greed=fg_due,
                    cached_fear_greed=self.fear_greed_value,
                )
                self.last_macro = now
                if fg_due and self.macro is not None:
                    self.fear_greed_value = self.macro.fear_greed
                    self.last_fg = now
            except Exception:
                log.exception("macro refresh failed — gate fails closed")
                self.macro = None

        # 3) on each completed 1m bar, check TF boundaries
        need = self._min_b