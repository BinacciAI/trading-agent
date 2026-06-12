"""Execution venues — paper, PancakeSwap spot (via TWAK), BSC perps.

Layer 2 of the sponsor stack is Trust Wallet Agent Kit (TWAK): self-custody
local signing with an optional autonomous mode (unlock once, then the agent
signs without per-transaction taps). The venue adapters below isolate ALL
chain interaction so the strategy/execution core never touches keys.

Live wiring checklist (Track 1):
1. Install TWAK from https://portal.trustwallet.com/ and run its MCP/REST
   endpoint locally; set BINACCI_TWAK_ENDPOINT.
2. Fund the wallet on BSC testnet first (BINACCI_USE_TESTNET=true).
3. PancakeSwap spot swaps route through TWAK's swap/sign primitives; perps
   route through the BSC perps integration.
4. Register the agent on-chain (ERC-8004 via `bnbagent`) — see chain.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol

import httpx

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
    def market_close(self, symbol: str, side: Side, qty: float) -> OrderResult: ...
    def balance_usd(self) -> float: ...


# --------------------------------------------------------------------------
# Paper venue — used by backtests, testnet dry-runs, and the demo loop
# --------------------------------------------------------------------------

@dataclass
class PaperVenue:
    name: str = "paper"
    starting_balance_usd: float = 1000.0
    slippage_pct: float = 0.02
    fee_pct: float = 0.05
    fills: list[dict] = field(default_factory=list)

    def place_limit(self, symbol: str, side: Side, price: float, notional_usd: float) -> OrderResult:
        fill = price * (1 + self.slippage_pct / 100) if side is Side.LONG else price * (1 - self.slippage_pct / 100)
        self.fills.append({"ts": datetime.utcnow().isoformat(), "symbol": symbol,
                           "side": side.value, "price": fill, "notional": notional_usd})
        return OrderResult(ok=True, venue=self.name, tx_or_id=f"paper-{len(self.fills)}",
                           fill_price=fill, detail="paper fill")

    def market_close(self, symbol: str, side: Side, qty: float) -> OrderResult:
        return OrderResult(ok=True, venue=self.name, tx_or_id=f"paper-close-{len(self.fills)}")

    def balance_usd(self) -> float:
        return self.starting_balance_usd


# --------------------------------------------------------------------------
# TWAK-backed venues
# --------------------------------------------------------------------------

class TWAKClient:
    """REST client for a locally running Trust Wallet Agent Kit endpoint.

    TWAK exposes MCP and REST; the agent loop uses REST for determinism.
    Endpoints below follow the tw-agent-skills reference layout; adjust to
    the installed TWAK version (`/health` probe on startup will tell you).
    """

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg
        self._client = httpx.Client(base_url=cfg.twak_endpoint, timeout=30.0) if cfg.twak_endpoint else None

    @property
    def available(self) -> bool:
        if self._client is None:
            return False
        try:
            return self._client.get("/health").status_code == 200
        except Exception:
            return False

    def swap(self, from_token: str, to_token: str, amount_usd: float, max_slippage_pct: float = 0.5) -> dict:
        assert self._client, "TWAK endpoint not configured (BINACCI_TWAK_ENDPOINT)"
        r = self._client.post("/swap", json={
            "chain": "bsc-testnet" if self.cfg.use_testnet else "bsc",
            "fromToken": from_token, "toToken": to_token,
            "amountUsd": amount_usd, "maxSlippagePct": max_slippage_pct,
            "dex": "pancakeswap",
        })
        r.raise_for_status()
        return r.json()

    def balance(self) -> dict:
        assert self._client, "TWAK endpoint not configured"
        r = self._client.get("/balance", params={"address": self.cfg.wallet_address})
        r.raise_for_status()
        return r.json()


@dataclass
class PancakeSpotVenue:
    """PancakeSwap spot via TWAK. Long-only: BUY token at level, SELL on exit.

    DEXes have no native limit orders — the agent emulates them: the
    orchestrator parks the level, and this venue executes a swap the moment
    the level is touched (same semantics the backtester uses).
    """

    twak: TWAKClient
    quote: str = "USDT"
    name: str = "pancake"

    def place_limit(self, symbol: str, side: Side, price: float, notional_usd: float) -> OrderResult:
        if side is not Side.LONG:
            return OrderResult(ok=False, venue=self.name, detail="spot venue is long-only")
        try:
            res = self.twak.swap(from_token=self.quote, to_token=symbol, amount_usd=notional_usd)
            return OrderResult(ok=True, venue=self.name, tx_or_id=res.get("txHash", ""),
                               fill_price=float(res.get("executionPrice", price)),
                               detail="swap executed on level touch")
        except Exception as e:  # pragma: no cover
            log.exception("pancake swap failed")
            return OrderResult(ok=False, venue=self.name, detail=str(e))

    def market_close(self, symbol: str, side: Side, qty: float) -> OrderResult:
        try:
            res = self.twak.swap(from_token=symbol, to_token=self.quote, amount_usd=0,
                                 max_slippage_pct=0.8)
            return OrderResult(ok=True, venue=self.name, tx_or_id=res.get("txHash", ""))
        except Exception as e:  # pragma: no cover
            return OrderResult(ok=False, venue=self.name, detail=str(e))

    def balance_usd(self) -> float:
        try:
            b = self.twak.balance()
            return float(b.get("totalUsd", 0.0))
        except Exception:
            return 0.0


@dataclass
class PerpsVenue:
    """BSC perps venue. Native limit orders + shorts + leverage — the
    closest fit to Binacci's margin/averaging model.

    Integration target: the perps surface referenced by the hackathon
    (PancakeSwap perps / BSC perps via BNB AI Agent SDK primitives). The
    adapter keeps the same Venue protocol so the engine doesn't care.
    """

    twak: TWAKClient
    name: str = "perps"
    leverage: float = 2.0

    def place_limit(self, symbol: str, side: Side, price: float, notional_usd: float) -> OrderResult:
        # TODO(live): wire to perps order endpoint once TWAK build is installed.
        return OrderResult(ok=False, venue=self.name,
                           detail="perps adapter pending TWAK install — see docs/SETUP.md")

    def market_close(self, symbol: str, side: Side, qty: float) -> OrderResult:
        return OrderResult(ok=False, venue=self.name, detail="perps adapter pending")

    def balance_usd(self) -> float:
        return 0.0


def make_venue(cfg: RuntimeConfig) -> Venue:
    if cfg.venue == "paper":
        return PaperVenue(starting_balance_usd=cfg.deposit_usd)
    twak = TWAKClient(cfg)
    if cfg.venue == "pancake":
        return PancakeSpotVenue(twak=twak)
    if cfg.venue == "perps":
        return PerpsVenue(twak=twak)
    raise ValueError(f"unknown venue: {cfg.venue}")
