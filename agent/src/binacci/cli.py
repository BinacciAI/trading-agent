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


def cmd_portfolio(args) -> int:
    """Backtest the whole BNB universe on one data source and print a table."""
    from .backtest import run_universe_backtest
    from .config import RuntimeConfig
    from .data import make_source

    cfg = StrategyConfig.load()
    rcfg = RuntimeConfig()
    syms = (cfg.symbols if args.symbols.lower() == "all"
            else [s.strip().upper() for s in args.symbols.split(",")])
    if args.limit:
        syms = syms[: args.limit]
    src = make_source(args.source, rcfg)
    res = run_universe_backtest(cfg, src, syms, Timeframe(args.timeframe),
                                bars=args.bars, deposit_usd=args.deposit,
                                eval_every=args.eval_every)
    print(f"\nUNIVERSE BACKTEST  source={args.source}  tf={res['timeframe']}  "
          f"risk={cfg.risk_mode.value}")
    print(f"{'MARKET':<8}{'TRADES':>7}{'WIN%':>7}{'PNL$':>9}{'RET%':>8}{'DD%':>7}{'PF':>8}")
    for p in res["per_symbol"]:
        pf = "inf" if p["profit_factor"] >= 999 else f"{p['profit_factor']:.2f}"
        print(f"{p['symbol']:<8}{p['trades']:>7}{p['win_rate_pct']:>7.1f}"
              f"{p['total_pnl_usd']:>9.2f}{p['return_pct']:>8.2f}{p['max_drawdown_pct']:>7.2f}{pf:>8}")
    if res["markets_skipped"]:
        print(f"\nskipped (insufficient data): {', '.join(res['markets_skipped'])}")
    print(f"\nAGGREGATE  markets={res['markets_tested']}  winners={res['winners']}  "
          f"losers={res['losers']}  trades={res['trades']}  win%={res['win_rate_pct']}  "
          f"total_pnl=${res['total_pnl_usd']}  avg_ret/mkt={res['avg_return_pct_per_market']}%  "
          f"worst_dd={res['worst_drawdown_pct']}%")
    return 0


def cmd_timebasis(args) -> int:
    """Show what a candle COUNT means in wall-clock time per timeframe."""
    import json as _json
    from .timebase import timebasis_table

    rows = timebasis_table(args.bars)
    if args.json:
        print(_json.dumps(rows, indent=2))
        return 0
    print(f"\nTIME BASIS — {args.bars} candles per timeframe\n")
    print(f"{'TF':>5}{'MIN/BAR':>9}{'TOTAL DAYS':>12}{'SPAN':>14}")
    for r in rows:
        print(f"{r['timeframe']:>5}{r['minutes_per_bar']:>9}"
              f"{r['total_days']:>12.2f}{r['span']:>14}")
    return 0


def cmd_fullbacktest(args) -> int:
    """All-universe, multi-timeframe backtest with strategy/market breakdown."""
    import json as _json
    from .backtest import run_full_backtest
    from .config import RuntimeConfig
    from .data import make_source

    cfg = StrategyConfig.load()
    if args.risk_mode:
        cfg.apply_risk_mode(args.risk_mode)
    rcfg = RuntimeConfig()
    syms = (cfg.symbols if args.symbols.lower() == "all"
            else [s.strip().upper() for s in args.symbols.split(",")])
    if args.limit:
        syms = syms[: args.limit]
    tfs = ([Timeframe(t.strip()) for t in args.timeframes.split(",")]
           if args.timeframes else None)
    src = make_source(args.source, rcfg)

    def _progress(done, total):
        print(f"  ...{done}/{total} runs", flush=True)

    res = run_full_backtest(cfg, src, syms, tfs, bars=args.bars,
                            deposit_usd=args.deposit, eval_every=args.eval_every,
                            risk_mode=args.risk_mode or None, progress=_progress)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(_json.dumps(res, indent=2))
        print(f"wrote {args.output}")

    c, pf = res["config"], res["portfolio"]
    print(f"\nFULL BACKTEST  source={args.source}  risk={c['risk_mode']}  "
          f"leverage={c['perps_leverage']}x  target_mult={c['perps_target_mult']}")
    print(f"universe={c['markets_in_universe']} markets x {len(c['timeframes'])} TFs "
          f"= {pf['runs_completed']}/{pf['runs_attempted']} runs  ({pf['runs_skipped']} skipped)")
    print(f"trades={pf['trades']}  win%={pf['win_rate_pct']}  pnl=${pf['total_pnl_usd']}  "
          f"avg_ret/run={pf['avg_return_pct_per_run']}%  worst_dd={pf['worst_drawdown_pct']}%")

    print("\nBY MARKET (book)")
    for k, v in res["by_market"].items():
        print(f"  {k:<6} trades={v['trades']:>5}  win%={v['win_rate_pct']:>5}  pnl=${v['total_pnl_usd']}")
    print("\nBY STRATEGY")
    for k, v in res["by_strategy"].items():
        print(f"  {k:<20} trades={v['trades']:>5}  win%={v['win_rate_pct']:>5}  pnl=${v['total_pnl_usd']}")
    print("\nBY TIMEFRAME (with time basis)")
    print(f"  {'TF':>5}{'SPAN':>14}{'MKTS':>6}{'TRADES':>8}{'WIN%':>7}{'PNL$':>11}")
    for tf, v in res["by_timeframe"].items():
        print(f"  {tf:>5}{v['timebasis']['span']:>14}{v['markets_tested']:>6}"
              f"{v['trades']:>8}{v['win_rate_pct']:>7}{v['total_pnl_usd']:>11.2f}")
    print("\nTOP MARKETS")
    for m in res["top_markets"][:10]:
        print(f"  {m['symbol']:<8} trades={m['trades']:>4}  win%={m['win_rate_pct']:>5}  pnl=${m['total_pnl_usd']}")
    return 0


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

    up = sub.add_parser("portfolio", help="backtest the whole universe on one source")
    up.add_argument("--symbols", default="all", help="'all' or comma list")
    up.add_argument("--timeframe", default="15m")
    up.add_argument("--bars", type=int, default=600)
    up.add_argument("--deposit", type=float, default=1000.0)
    up.add_argument("--source", default="synthetic", help="synthetic | cmc | checkpoint")
    up.add_argument("--limit", type=int, default=0, help="cap number of markets (0=all)")
    up.add_argument("--eval-every", dest="eval_every", type=int, default=1)
    up.set_defaults(fn=cmd_portfolio)

    fb = sub.add_parser("fullbacktest",
                        help="all-universe, multi-timeframe backtest w/ strategy+market breakdown")
    fb.add_argument("--symbols", default="all", help="'all' or comma list")
    fb.add_argument("--timeframes", default="", help="comma list e.g. 3m,15m,4h (default: cfg entry TFs)")
    fb.add_argument("--bars", type=int, default=1500)
    fb.add_argument("--deposit", type=float, default=1000.0)
    fb.add_argument("--source", default="synthetic", help="synthetic | cmc | checkpoint")
    fb.add_argument("--risk-mode", dest="risk_mode", default="",
                    help="conservative | balanced | aggressive (sets leverage tier)")
    fb.add_argument("--limit", type=int, default=0, help="cap number of markets (0=all)")
    fb.add_argument("--eval-every", dest="eval_every", type=int, default=1)
    fb.add_argument("--output", default="", help="write full JSON report to this path")
    fb.set_defaults(fn=cmd_fullbacktest)

    tb = sub.add_parser("timebasis", help="show wall-clock span of a candle count per timeframe")
    tb.add_argument("--bars", type=int, default=1500)
    tb.add_argument("--json", action="store_true")
    tb.set_defaults(fn=cmd_timebasis)

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
