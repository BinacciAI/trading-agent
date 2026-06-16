"""Sentinel agent — market-anomaly safety net.

Watches the price feed every poll for events the trading rules shouldn't trade
through: stablecoin DE-PEGS, single-tick FLASH moves, and BROAD crashes (many
markets dislocating at once = a market-wide event / feed glitch). On a critical
event it HALTS new opens (existing positions keep being managed/closed). The
operator clears it via /venue/resume after reviewing. This sits above the 30%
drawdown kill switch: it reacts to the *market*, not just our book.
"""

from __future__ import annotations

import os
import time
from collections import deque

_DEFAULT_STABLES = "USDT,USDC,DAI,TUSD,FDUSD,USDD,USD1,DUSD,USDX,EURI,XAUT"


def _f(env: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(env, default)))
    except (TypeError, ValueError):
        return default


class Sentinel:
    def __init__(self) -> None:
        self.depeg_pct = _f("BINACCI_DEPEG_PCT", 2.0)        # stable off $1 by > this
        self.crash_pct = _f("BINACCI_CRASH_PCT", 15.0)       # single-tick move > this
        self.broad_n = int(_f("BINACCI_BROAD_CRASH_N", 8))   # N flash moves at once = market event
        self.stables = set(x.strip().upper() for x in
                           (os.environ.get("BINACCI_STABLES") or _DEFAULT_STABLES).split(",") if x.strip())
        self._last: dict[str, float] = {}
        self.alerts: deque = deque(maxlen=60)
        self.tripped = False
        self.last_reason = ""

    def check(self, prices: dict[str, float]) -> dict:
        new: list[dict] = []
        crashed: list[str] = []
        now = time.time()
        for sym, px in prices.items():
            if not px or px <= 0:
                continue
            if sym.upper() in self.stables and abs(px - 1.0) * 100.0 > self.depeg_pct:
                new.append({"ts": now, "type": "depeg", "symbol": sym, "detail": f"${px:.4f} off peg"})
            prev = self._last.get(sym)
            if prev and prev > 0:
                move = (px - prev) / prev * 100.0
                if abs(move) > self.crash_pct:
                    crashed.append(sym)
                    new.append({"ts": now, "type": "flash_move", "symbol": sym, "detail": f"{move:+.1f}% in one tick"})
            self._last[sym] = px
        broad = len(crashed) >= self.broad_n
        depeg = any(a["type"] == "depeg" for a in new)
        critical = depeg or broad
        for a in new:
            self.alerts.appendleft(a)
        if critical:
            self.tripped = True
            self.last_reason = ("stablecoin de-peg" if depeg else f"broad crash ({len(crashed)} markets)")
        return {"critical": critical, "broad_crash": broad, "depeg": depeg,
                "crashed": crashed, "new_alerts": new, "reason": self.last_reason if critical else ""}

    def status(self) -> dict:
        return {"armed": True, "tripped": self.tripped, "last_reason": self.last_reason,
                "thresholds": {"depeg_pct": self.depeg_pct, "crash_pct": self.crash_pct, "broad_n": self.broad_n},
                "recent_alerts": list(self.alerts)[:20], "stables_watched": sorted(self.stables)}
