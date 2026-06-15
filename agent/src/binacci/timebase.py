"""Time-basis helpers — translate a candle/bar COUNT into the wall-clock
span it actually represents on a given timeframe.

A backtest "on 1500 bars" means very different things per timeframe: 1500 ×
3m is a few days, 1500 × 1d is over four years. Reporting bar counts without
the time basis hides that, so every backtest summary now carries the span and
the dashboard can render it. Pure functions, no I/O — trivially testable.
"""

from __future__ import annotations

from datetime import timedelta

from .config import Timeframe

#: Average calendar lengths used only for HUMANIZING a span into
#: years/months/weeks/days. Bar math itself is exact (bars × tf.minutes).
_MIN_PER_HOUR = 60
_MIN_PER_DAY = 60 * 24
_MIN_PER_WEEK = _MIN_PER_DAY * 7
_MIN_PER_MONTH = _MIN_PER_DAY * 30.437  # mean Gregorian month
_MIN_PER_YEAR = _MIN_PER_DAY * 365.25


def bars_to_minutes(bars: int, tf: Timeframe) -> int:
    """Exact wall-clock minutes spanned by ``bars`` candles on ``tf``."""
    return int(bars) * tf.minutes


def bars_to_timedelta(bars: int, tf: Timeframe) -> timedelta:
    return timedelta(minutes=bars_to_minutes(bars, tf))


def humanize_duration(minutes: float) -> str:
    """Compact human label for a span in minutes, picking the largest unit
    that reads naturally for a trading horizon: '15.6 days', '8.2 months',
    '4.1 years'. Weeks are intentionally skipped — days up to ~3 months is the
    more intuitive unit for candle spans."""
    minutes = float(minutes)
    if minutes < _MIN_PER_HOUR:
        return f"{minutes:.0f} min"
    if minutes < _MIN_PER_DAY:
        return f"{minutes / _MIN_PER_HOUR:.1f} hours"
    if minutes < _MIN_PER_DAY * 90:
        return f"{minutes / _MIN_PER_DAY:.1f} days"
    if minutes < _MIN_PER_YEAR:
        return f"{minutes / _MIN_PER_MONTH:.1f} months"
    return f"{minutes / _MIN_PER_YEAR:.1f} years"


def timebasis_row(bars: int, tf: Timeframe) -> dict:
    """One {timeframe, bars, minutes, span} record."""
    mins = bars_to_minutes(bars, tf)
    return {
        "timeframe": tf.value,
        "minutes_per_bar": tf.minutes,
        "bars": int(bars),
        "total_minutes": mins,
        "total_days": round(mins / _MIN_PER_DAY, 3),
        "span": humanize_duration(mins),
    }


def timebasis_table(bars: int, timeframes: list[Timeframe] | None = None) -> list[dict]:
    """Time basis for ``bars`` candles across each timeframe, shortest first.
    Defaults to every timeframe Binacci knows about."""
    tfs = list(timeframes) if timeframes else list(Timeframe)
    tfs = sorted(tfs, key=lambda t: t.minutes)
    return [timebasis_row(bars, tf) for tf in tfs]
