"""BNB Chain integration — ERC-8004 identity + APEX (ERC-8183) commerce.

Layer 3 of the sponsor stack. Two independent capabilities:

* **ERC-8004 registration** — mints an on-chain identity (gas-free on BSC
  testnet via MegaFuel paymaster) so the agent is discoverable.
* **APEX server** — the business model beyond the hackathon: other agents
  pay (escrowed, UMA-verified) for Binacci strategy specs and signal
  evaluations. The Track 2 skill output IS the APEX deliverable.

Requires `pip install "bnbagent[server,ipfs]"` (extra: `chain`). All
imports are lazy so the core runs without chain deps.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)


def register_agent_identity(
    name: str = "binacci-agent",
    description: str = (
        "Reaction-based autonomous trading agent. 5-simulation analysis, "
        "deterministic risk engine (30/70 margin, 5-slot cap, 30% kill switch). "
        "Sells backtestable strategy specs via APEX."
    ),
    a2a_card_url: str = "",
    network: str = "bsc-testnet",
) -> Optional[dict]:
    """One-time ERC-8004 registration. Returns {'agentId', 'transactionHash'}."""
    try:
        from bnbagent import AgentEndpoint, ERC8004Agent, EVMWalletProvider
    except ImportError:
        log.error("bnbagent not installed — pip install 'bnbagent[server,ipfs]'")
        return None

    password = (os.environ.get("WALLET_PASSWORD")
                or os.environ.get("BINACCI_WALLET_PASSWORD")
                or os.environ.get("TWAK_WALLET_PASSWORD"))
    private_key = (os.environ.get("PRIVATE_KEY")
                   or os.environ.get("BINACCI_AGENT_PRIVATE_KEY"))
    if not password:
        log.error("ERC-8004 register: no wallet password "
                  "(set BINACCI_WALLET_PASSWORD or reuse TWAK_WALLET_PASSWORD)")
        return None
    wallet = EVMWalletProvider(password=password, private_key=private_key)
    sdk = ERC8004Agent(network=network, wallet_provider=wallet)
    endpoints = []
    if a2a_card_url:
        endpoints.append(AgentEndpoint(name="A2A", endpoint=a2a_card_url, version="0.3.0"))
    uri = sdk.generate_agent_uri(name=name, description=description, endpoints=endpoints)
    result = sdk.register_agent(agent_uri=uri)
    log.info("ERC-8004 registered: agentId=%s tx=%s", result["agentId"], result["transactionHash"])
    return result


def execute_strategy_job(job: dict) -> str:
    """APEX `on_job` callback — the paid deliverable.

    A client funds a job whose description is a JSON request like:
    ``{"task": "strategy_spec", "symbol": "BNB", "timeframe": "4h"}``
    We run the Track 2 skill and return the spec (stored to IPFS by the
    APEX server; only the hash goes on-chain).
    """
    from .config import StrategyConfig, Timeframe
    from .skill import generate_strategy_spec

    try:
        req: dict[str, Any] = json.loads(job.get("description", "") or "{}")
    except json.JSONDecodeError:
        req = {}

    symbol = str(req.get("symbol", "BNB")).upper()
    tf = Timeframe(req.get("timeframe", "4h"))
    cfg = StrategyConfig()
    spec = generate_strategy_spec(cfg, symbol=symbol, tf=tf)
    return json.dumps(spec, indent=2, default=str)


def maybe_auto_register() -> Optional[dict]:
    """Opt-in ERC-8004 registration at startup (BINACCI_AUTO_REGISTER=true).

    Idempotent: stores the minted agentId in the data dir and skips when
    already registered. Gas-free on bsc-testnet via MegaFuel paymaster.
    """
    import json
    from pathlib import Path

    if os.environ.get("BINACCI_AUTO_REGISTER", "").lower() not in ("1", "true", "yes"):
        return None
    marker = Path(os.environ.get("BINACCI_DATA_DIR", "/tmp/binacci-data")) / "erc8004.json"
    if marker.exists():
        log.info("ERC-8004 already registered: %s", marker.read_text())
        return json.loads(marker.read_text())
    has_pw = bool(os.environ.get("WALLET_PASSWORD") or os.environ.get("BINACCI_WALLET_PASSWORD")
                  or os.environ.get("TWAK_WALLET_PASSWORD"))
    has_key = bool(os.environ.get("PRIVATE_KEY") or os.environ.get("BINACCI_AGENT_PRIVATE_KEY")
                   or marker.parent.joinpath(".keystore").exists())
    if not (has_pw and has_key):
        log.warning("auto-register skipped: need a wallet password + an agent PRIVATE_KEY "
                    "(BINACCI_AGENT_PRIVATE_KEY). Gas-free on bsc-testnet via MegaFuel.")
        return None
    network = "bsc-testnet" if os.environ.get("BINACCI_USE_TESTNET", "true").lower() in ("1", "true", "yes") else "bsc"
    result = register_agent_identity(network=network,
                                     a2a_card_url=os.environ.get("BINACCI_AGENT_CARD_URL", ""))
    if result:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"agentId": result.get("agentId"),
                                      "tx": result.get("transactionHash"),
                                      "network": network}))
    return result


def register_now() -> dict:
    """On-demand ERC-8004 registration (POST /chain/register). Idempotent —
    returns the existing identity if already minted."""
    import json
    from pathlib import Path

    marker = Path(os.environ.get("BINACCI_DATA_DIR", "/tmp/binacci-data")) / "erc8004.json"
    if marker.exists():
        try:
            return {"ok": True, "already": True, **json.loads(marker.read_text())}
        except Exception:
            pass
    network = "bsc-testnet" if os.environ.get("BINACCI_USE_TESTNET", "true").lower() in ("1", "true", "yes") else "bsc"
    res = register_agent_identity(network=network,
                                  a2a_card_url=os.environ.get("BINACCI_AGENT_CARD_URL", ""))
    if not res:
        return {"ok": False,
                "error": "registration failed — ensure bnbagent is installed and "
                         "BINACCI_AGENT_PRIVATE_KEY + a wallet password are set",
                "network": network}
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"agentId": res.get("agentId"),
                                      "tx": res.get("transactionHash"), "network": network}))
    except Exception:
        log.exception("could not persist erc8004 marker")
    return {"ok": True, "agentId": res.get("agentId"),
            "tx": res.get("transactionHash"), "network": network}


def create_agent_app():
    """FastAPI app: Binacci status API + APEX server mounted at /apex."""
    from .api import build_app

    app = build_app()
    try:
        from bnbagent.apex.server import create_apex_app

        apex = create_apex_app(on_job=execute_strategy_job)
        app.mount("/apex", apex)
        log.info("APEX server mounted at /apex")
    except ImportError:
        log.warning("bnbagent not installed — running without APEX endpoints")
    except Exception:
        log.exception("APEX mount failed — continuing without it")
    try:
        maybe_auto_register()
    except Exception:
        log.exception("ERC-8004 auto-register failed — continuing")
    return app
