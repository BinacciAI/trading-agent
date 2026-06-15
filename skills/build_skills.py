"""Generate the installable Binacci strategy SKILL.md packages.

Single source of truth = ``binacci.skill.STRATEGY_META`` + the live config,
so the packaged skills can never drift from the code that backs them. Run:

    PYTHONPATH=agent/src python skills/build_skills.py

Each strategy gets a folder ``skills/<skill-name>/SKILL.md``. The family
index is written to ``skills/README.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "agent" / "src"))

from binacci.config import StrategyConfig, Timeframe  # noqa: E402
from binacci.skill import (  # noqa: E402
    STRATEGY_META, SKILL_VERSION, skill_name, _strategy_params,
)
from binacci.strategies import ALL_STRATEGY_NAMES  # noqa: E402


def _flatten(d, prefix=""):
    out = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.extend(_flatten(v, key + "."))
        else:
            out.append((key, v))
    return out


def skill_md(strategy: str, cfg: StrategyConfig) -> str:
    m = STRATEGY_META[strategy]
    name = skill_name(strategy)
    gates = " → ".join(m["gates"])
    param_rows = "\n".join(f"| `{k}` | `{v}` |" for k, v in _flatten(_strategy_params(strategy, cfg)))
    macro = "required" if m["requires_macro"] else "not required (counter-trend)"
    return f"""---
name: {name}
description: >-
  Track-2 CMC Strategy Skill. {m['title']} — generates a backtestable trading
  strategy spec from CoinMarketCap market data (quotes, OHLCV, global metrics).
  Ships a machine-readable, replayable spec + verification backtest, not a live
  agent. {m['entry_logic']}
version: {SKILL_VERSION}
---

# {m['title']} — Binacci Strategy Skill

> **Track 2 (Strategy Skills).** Input: a symbol + timeframe and CMC market
> data. Output: a deterministic, **backtestable** strategy spec — rules,
> parameters, current market state, and a verification backtest run by the
> same engine as the live Binacci agent.

## Philosophy

{m['philosophy']}

## Entry logic

{m['entry_logic']}

**Gate chain:** `{gates}`
**Macro gate:** {macro}.

## Shared risk model (identical across every Binacci strategy)

Every strategy feeds ONE deterministic execution engine — the AI is an
executor, never a risk-taker:

- 30/70 margin model: 30% of deposit reserved, entry = 0.35% of deposit.
- Averaging x4 then x2, **only at a level and only while in drawdown** (~3% position cap).
- 5 concurrent slots, with smart slot return when the trailing SL is already green.
- Stepped trailing SL (trigger +0.4% → SL +0.2%, then +0.1% steps) — a position almost cannot close red.
- 30% aggregate-drawdown kill switch closes everything.
- Positions are unique per `(symbol, timeframe, strategy)`, so strategies run concurrently without colliding.

## Parameters

| Parameter | Default |
|---|---|
{param_rows}

## Generate a spec

CLI:

```bash
binacci spec --strategy {strategy} --symbol BNB --timeframe 4h
```

API (when the agent server is running):

```bash
curl "http://localhost:8000/spec?strategy={strategy}&symbol=BNB&timeframe=4h"
```

Python:

```python
from binacci.config import StrategyConfig, Timeframe
from binacci.skill import generate_strategy_spec
spec = generate_strategy_spec(StrategyConfig(), symbol="BNB",
                              tf=Timeframe.H4, strategy="{strategy}")
```

## Output shape

```jsonc
{{
  "skill": "{name}",
  "strategy_name": "{strategy}",
  "strategy":   {{ "entry_chain": [...], "parameters": {{...}}, "execution": {{...}} }},
  "market_state": {{ "price": ..., "reference": ..., "proposal": {{ "in_setup": true|false, "level_price": ... }} }},
  "backtest":   {{ "trades": N, "win_rate_pct": ..., "return_pct": ..., "max_drawdown_pct": ..., "sharpe": ... }},
  "provenance": {{ "config_fingerprint": "…", "engine": "binacci.backtest (same engine as live agent)" }}
}}
```

## Data dependencies (CMC L1)

- `v2/cryptocurrency/quotes/latest` — price + 24h volume
- `v2/cryptocurrency/ohlcv/historical` — candles
- `v1/global-metrics/quotes/latest` — totalCap, BTC.D, USDT.D (macro gate)
- CMC MCP technicals (RSI / Fibonacci / support-resistance) — cross-check

## Monetization (optional)

x402 pay-per-call and/or APEX (ERC-8183) escrowed jobs on BSC.

---
*Binacci strategy family · v{SKILL_VERSION} · contact: brandononchain@gmail.com*
"""


def index_md(cfg: StrategyConfig) -> str:
    rows = "\n".join(
        f"| [{STRATEGY_META[n]['title']}]({skill_name(n)}/SKILL.md) | `{n}` | "
        f"{'yes' if STRATEGY_META[n]['requires_macro'] else 'no'} | {STRATEGY_META[n]['philosophy']} |"
        for n in ALL_STRATEGY_NAMES
    )
    return f"""# Binacci Strategy Skills (CMC Hackathon — Track 2)

A family of **backtestable strategy skills** for the BNB Chain × CoinMarketCap
× Trust Wallet AI Agent Hackathon. Each skill turns CMC market data into a
deterministic, replayable strategy spec + verification backtest — "quant
research", not a live agent. All specs are produced by the **same engine** the
live Binacci Track-1 agent trades with, so a spec's backtest is exactly what
the agent would have done.

## Skills

| Skill | id | macro gate | philosophy |
|---|---|---|---|
{rows}

Plus a **portfolio** spec that runs every strategy together:

```bash
binacci spec --portfolio --symbol BNB --timeframe 4h
curl "http://localhost:8000/spec?strategy=portfolio&symbol=BNB&timeframe=4h"
```

## Why a family, not one strategy

One strategy is one opinion. Binacci runs a portfolio of orthogonal
strategies over every (symbol, timeframe) stream, each proposing limit
entries into the same hard risk engine. More independent reasons to be in a
market = a wider opportunity surface, with the slot cap and kill switch still
bounding total exposure. Positions are keyed per `(symbol, timeframe,
strategy)`, so the strategies never collide.

## Regenerate these docs

```bash
PYTHONPATH=agent/src python skills/build_skills.py
```

*Generated from `binacci.skill.STRATEGY_META` — edit the code, not the docs.*
"""


def main() -> int:
    cfg = StrategyConfig()
    for n in ALL_STRATEGY_NAMES:
        d = ROOT / skill_name(n)
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(skill_md(n, cfg), encoding="utf-8")
        print("wrote", d / "SKILL.md")
    (ROOT / "README.md").write_text(index_md(cfg), encoding="utf-8")
    print("wrote", ROOT / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
