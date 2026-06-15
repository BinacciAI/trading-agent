"""Execution venues — paper, PancakeSwap spot via TWAK CLI, BSC perps.

Layer 2 of the sponsor stack: Trust Wallet Agent Kit. TWAK ships as a CLI
(`npm i -g @trustwallet/cli`) with HMAC-authenticated API credentials from
portal.trustwallet.com and a locally-encrypted non-custodial wallet. Keys
never leave the host. The Docker image installs Node + the CLI; entrypoint
runs `twak init` from TWAK_ACCESS_ID / TWAK_HMAC_SECRET env vars.

Swap semantics (verified against tw-agent-skills references/swap.md):
    twak swap <FROM> <TO> --chain bsc --usd <amount> --slippage <pct> --json
BSC chain key is `bsc` (mainnet). `bsctestnet` supports ERC-20 + ERC-8004/
8183 contract calls but NOT swaps — so spot rehearsal happens on the paper
venue and first real swaps are dust-sized on mainnet.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol

from .config import RuntimeConfig
from .models import Side

log = logging.getLogger(__name__)


@dataclass(slots=True)
class OrderResult:
    ok: bool
    venue: str
    tx_or_id: str = ""
    fill_price: float = 0.0
    detail: str = ""


class Venue(Protocol):
    name: str

    def place_limit(self, symbol: str, side: Side, price: float, notional_usd: float) -> OrderResult: ...
    def market_close(self, symbol: str, side: Side, notional_usd: float) -> OrderResult: ...
    def balance_usd(self) -> float: ...


# --------------------------------------------------------------------------
# Paper venue — backtests, soak runs, and the default live mode
# --------------------------------------------------------------------------

@dataclass
class PaperVenue:
    name: str = "paper"
    starting_balance_usd: float = 1000.0
    slippage_pct: float = 0.02
    fills: list[dict] = field(default_factory=list)

    def place_limit(self, symbol: str, side: Side, price: float, notional_usd: float) -> OrderResult:
        fill = price * (1 + self.slippage_pct / 100) if side is Side.LONG else price * (1 - self.slippage_pct / 100)
        self.fills.append({"ts": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
                           "side": side.value, "price": fill, "notional": notional_usd})
        return OrderResult(ok=True, venue=self.name, tx_or_id=f"paper-{len(self.fills)}",
                           fill_price=fill, detail="paper fill")

    def market_close(self, symbol: str, side: Side, notional_usd: float) -> OrderResult:
        self.fills.append({"ts": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
                           "side": "close", "notional": notional_usd})
        return OrderResult(ok=True, venue=self.name, tx_or_id=f"paper-close-{len(self.fills)}")

    def balance_usd(self) -> float:
        return self.starting_balance_usd


# --------------------------------------------------------------------------
# TWAK CLI adapter
# --------------------------------------------------------------------------

class TwakCLI:
    """Thin subprocess wrapper around the `twak` CLI (JSON mode).

    Credentials come from env (TWAK_ACCESS_ID / TWAK_HMAC_SECRET) persisted
    by `twak init` at container start; the wallet password resolves from
    TWAK_WALLET_PASSWORD. Secrets are never passed as CLI arguments.
    """

    def __init__(self, timeout_s: int = 90):
        self.timeout_s = timeout_s

    @property
    def installed(self) -> bool:
        return shutil.which("twak") is not None

    def run(self, *args: str) -> dict:
        cmd = ["twak", *args, "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            return {"error": f"twak timed out after {self.timeout_s}s", "errorCode": "TIMEOUT"}
        out = proc.stdout.strip() or proc.stderr.strip()
        try:
            return json.loads(out) if out else {"error": "empty output"}
        except json.JSONDecodeError:
            return {"error": out[:500], "errorCode": "NON_JSON"}

    def auth_ok(self) -> bool:
        return bool(self.run("auth", "status").get("configured"))

    def wallet_ok(self) -> bool:
        res = self.run("wallet", "status")
        return bool(res.get("exists") or res.get("address") or res.get("configured"))

    def quote_swap(self, frm: str, to: str, usd: float, chain: str = "bsc",
                   slippage_pct: float = 0.5) -> dict:
        return self.run("swap", frm, to, "--chain", chain, "--usd", f"{usd:.2f}",
                        "--slippage", str(slippage_pct), "--quote-only")

    def swap(self, frm: str, to: str, usd: float, chain: str = "bsc",
             slippage_pct: float = 0.5) -> dict:
        return self.run("swap", frm, to, "--chain", chain, "--usd", f"{usd:.2f}",
                        "--slippage", str(slippage_pct))

    def balance(self, chain: str = "bsc") -> dict:
        return self.run("wallet", "balance", "--chain", chain)

    # ---- Track-1 on-chain competition registration ----
    def compete_register(self) -> dict:
        """`twak compete register` — resolves the agent wallet address and
        submits the on-chain registration tx to the competition contract."""
        return self.run("compete", "register")

    def compete_status(self) -> dict:
        return self.run("compete", "status")


# --------------------------------------------------------------------------
# PancakeSwap spot via TWAK (BSC mainnet)
# --------------------------------------------------------------------------

@dataclass
class PancakeSpotVenue:
    """Long-only spot: buy SYMBOL with USDT at the level, sell back on exit.

    DEXes have no native limit orders — the orchestrator parks the level
    and this venue executes the swap the moment the level is touched (the
    identical semantics the backtester fills with).
    """

    rcfg: RuntimeConfig
    twak: TwakCLI = field(default_factory=TwakCLI)
    quote: str = "USDT"
    max_slippage_pct: float = 0.5
    name: str = "pancake"

    def preflight(self) -> tuple[bool, str]:
        if not self.twak.installed:
            return False, "twak CLI not installed"
        if not self.twak.auth_ok():
            return False, "twak not authenticated (TWAK_ACCESS_ID/TWAK_HMAC_SECRET)"
        if not self.twak.wallet_ok():
            return False, "twak wallet missing (entrypoint creates it from TWAK_WALLET_PASSWORD)"
        if self.rcfg.use_testnet:
            return False, "swaps unsupported on bsctestnet — set BINACCI_USE_TESTNET=false"
        return True, "ready"

    def place_limit(self, symbol: str, side: Side, price: float, notional_usd: float) -> OrderResult:
        if side is not Side.LONG:
            return OrderResult(ok=False, venue=self.name, detail="spot venue is long-only")
        ok, why = self.preflight()
        if not ok:
            return OrderResult(ok=False, venue=self.name, detail=f"preflight: {why}")
        res = self.twak.swap(self.quote, symbol, usd=notional_usd,
                             chain="bsc", slippage_pct=self.max_slippage_pct)
        if res.get("error"):
            log.error("pancake buy failed: %s", res)
            return OrderResult(ok=False, venue=self.name, detail=str(res.get("error"))[:300])
        return OrderResult(
            ok=True, venue=self.name,
            tx_or_id=str(res.get("txHash") or res.get("hash") or res.get("transactionHash") or ""),
            fill_price=float(res.get("executionPrice") or res.get("price") or price),
            detail="swap executed on level touch",
        )

    def market_close(self, symbol: str, side: Side, notional_usd: float) -> OrderResult:
        ok, why = self.preflight()
        if not ok:
            return OrderResult(ok=False, venue=self.name, detail=f"preflight: {why}")
        res = self.twak.swap(symbol, self.quote, usd=notional_usd,
                             chain="bsc", slippage_pct=self.max_slippage_pct * 1.6)
        if res.get("error"):
            log.error("pancake close failed: %s", res)
            return OrderResult(ok=False, venue=self.name, detail=str(res.get("error"))[:300])
        return OrderResult(ok=True, venue=self.name,
                           tx_or_id=str(res.get("txHash") or res.get("hash") or ""))

    def balance_usd(self) -> float:
        res = self.twak.balance("bsc")
        try:
            return float(res.get("totalUsd") or res.get("totalUSD") or 0.0)
        except (TypeError, ValueError):
            return 0.0


@dataclass
class PerpsVenue:
    """BSC perps — roadmap. The twak CLI surface (v. June 2026) exposes
    spot swaps, transfers, ERC-20, x402 and automations, but not perps
    order placement; perps integration lands via the BNB AI Agent SDK
    primitives post-hackathon. Honest stub: never silently no-ops."""

    rcfg: RuntimeConfig
    name: str = "perps"

    def place_limit(self, symbol: str, side: Side, price: float, notional_usd: float) -> OrderResult:
        return OrderResult(ok=False, venue=self.name,
                           detail="perps venue is roadmap — use paper or pancake")

    def market_close(self, symbol: str, side: Side, notional_usd: float) -> OrderResult:
        return OrderResult(ok=False, venue=self.name, detail="perps venue is roadmap")

    def balance_usd(self) -> float:
        return 0.0


def make_venue(cfg: RuntimeConfig) -> Venue:
    if cfg.venue == "paper":
        return PaperVenue(starting_balance_usd=cfg.deposit_usd)
    if cfg.venue == "pancake":
        return PancakeSpotVenue(rcfg=cfg)
    if cfg.venue == "perps":
        return PerpsVenue(rcfg=cfg)
    raise ValueError(f"unknown venue: {cfg.venue}")
