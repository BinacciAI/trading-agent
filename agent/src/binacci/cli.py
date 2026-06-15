"""CLI — `binacci backtest | spec | paper | serve | register`."""

from __future__ import annotations

import argparse
import json
import sys

from .config import RuntimeConfig, StrategyConfig, Timeframe
from .data import SyntheticSource


def cmd_backtest(args) -> int:
    from .backtest import run_backtest

    cfg = StrategyConfig()
    src = SyntheticSource(seed=args.seed)
    res = run_backtest(cfg, src, args.symbol.upper(), Timeframe(args.timeframe),
                       bars=args.bars, deposit_usd=args.deposit)
    print(json.dumps(res.summary(), indent=2))
    if args.trades:
        print(json.dumps(res.trade_log, indent=2))
    return 0


def cmd_spec(args) -> int:
    from .skill import generate_portfolio_spec, generate_strategy_spec

    cfg = StrategyConfig()
    if getattr(args, "portfolio", False) or args.strategy == "portfolio":
        spec = generate_portfolio_spec(cfg, symbol=args.symbol.upper(),
                                       tf=Timeframe(args.timeframe),
                                       backtest_bars=args.bars)
    else:
        spec = generate_strategy_spec(cfg, symbol=args.symbol.upper(),
                                      tf=Timeframe(args.timeframe),
                                      backtest_bars=args.bars,
                                      strategy=args.strategy)
    out = json.dumps(spec, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"spec written to {args.output}")
    else:
        print(out)
    return 0


def cmd_paper(args) -> int:
    """Multi-symbol paper-trading session over synthetic or CSV data —
    exercises slots + kill switch across symbols."""
    from .execution import ExecutionEngine
    from .indicators import to_dataframe
    from .orchestrator import Orchestrator

    cfg = StrategyConfig()
    rcfg = RuntimeConfig()
    src = SyntheticSource(seed=args.seed)
    tf = Timeframe(args.timeframe)
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    engine = ExecutionEngine(cfg, deposit_usd=args.deposit)
    orch = Orchestrator(cfg, engine)
    orch.cfg.macro.enabled = False  # no live macro feed in paper mode

    data = {s: src.history(s, tf, args.bars) for s in symbols}
    warmup = 200
    for s in symbols:
        orch.cold_start(s, tf, to_dataframe(data[s][:warmup]))

    n = min(len(v) for v in data.values())
    for i in range(warmup, n):
        prices = {s: data[s][i].close for s in symbols}
        for s in symbols:
            window = data[s][max(0, i - 400): i + 1]
            df = to_dataframe(window)
            orch.update_references(s, tf, df)
            orch.evaluate(s, tf, df, ts=data[s][i].ts)
            orch.on_candle(s, tf, data[s][i], prices)

    print(json.dumps(engine.snapshot(prices), indent=2))
    print(f"closed trades: {len(engine.closed)}")
    by_strat: dict[str, list[float]] = {}
    for t in engine.closed:
        by_strat.setdefault(t.position.meta.get("strategy", "reaction"), []).append(t.pnl_usd)
    print("by strategy:")
    for name, pnls in sorted(by_strat.items()):
        print(f"  {name:20} trades={len(pnls):3d} pnl={sum(pnls):+8.2f} USD")
    for t in engine.closed[-10:]:
        strat = t.position.meta.get("strategy", "reaction")
        print(f"  {t.position.symbol:6} {strat:18} {t.reason:>14} {t.pnl_usd:+8.2f} USD")
    return 0


def cmd_strategies(args) -> int:
    from .skill import strategy_catalog

    print(json.dumps(strategy_catalog(), indent=2))
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .chain import create_agent_app

    rcfg = RuntimeConfig()
    uvicorn.run(create_agent_app(), host=rcfg.api_host, port=args.port or rcfg.api_port)
    return 0


def cmd_register(args) -> int:
    from .chain import register_agent_identity

    res = register_agent_identity(network=args.network, a2a_card_url=args.card_url)
    print(json.dumps(res, indent=2) if res else "registration failed — see logs")
    return 0 if res else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="binacci", description="Binacci agent CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backtest", help="run a single-symbol backtest")
    b.add_argument("--symbol", default="BNB")
    b.add_argument("--timeframe", default="4h")
    b.add_argument("--bars", type=int, default=2000)
    b.add_argument("--deposit", type=float, default=1000.0)
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--trades", action="store_true")
    b.set_defaults(fn=cmd_backtest)

    s = sub.add_parser("spec", help="generate a Track 2 strategy spec")
    s.add_argument("--symbol", default="BNB")
    s.add_argument("--timeframe", default="4h")
    s.add_argument("--bars", type=int, default=1500)
    s.add_argument("--strategy", default="reaction",
                   help="reaction | momentum_breakout | mean_reversion | "
                        "trend_follow | volatility_squeeze | portfolio")
    s.add_argument("--portfolio", action="store_true",
                   help="emit one spec covering the whole active portfolio")
    s.add_argument("--output", default="")
    s.set_defaults(fn=cmd_spec)

    st = sub.add_parser("strategies", help="list the strategy catalog")
    st.set_defaults(fn=cmd_strategies)

    pp = sub.add_parser("paper", help="multi-symbol paper session")
    pp.add_argument("--symbols", default="BNB,BTC,ETH,CAKE,SOL")
    pp.add_argument("--timeframe", default="15m")
    pp.add_argument("--bars", type=int, default=3000)
    pp.add_argument("--deposit", type=float, default=1000.0)
    pp.add_argument("--seed", type=int, default=7)
    pp.set_defaults(fn=cmd_paper)

    sv = sub.add_parser("serve", help="run API + APEX server")
    sv.add_argument("--port", type=int, default=0)
    sv.set_defaults(fn=cmd_serve)

    rg = sub.add_parser("register", help="ERC-8004 on-chain registration")
    rg.add_argument("--network", default="bsc-testnet")
    rg.add_argument("--card-url", default="")
    rg.set_defaults(fn=cmd_register)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
