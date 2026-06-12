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

    wallet = EVMWalletProvider(
        password=os.environ["WALLET_PASSWORD"],
        private_key=os.environ.get("PRIVATE_KEY"),  # first run only
    )
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
    return app
