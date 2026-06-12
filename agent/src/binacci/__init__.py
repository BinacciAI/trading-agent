"""Binacci Agent — reaction-based autonomous trading.

Two halves, strictly separated (per Binacci strategy doc):

* **Analysis** — strategy, filters, entry point. Five simulations decide
  *where* to enter. AI is an executor only; it never invents or edits
  strategy parameters.
* **Execution** — margin, averaging, stops, risk limits. A deterministic
  engine decides *how* to open, manage, and exit.

Built for the BNB Chain x CoinMarketCap x Trust Wallet AI Agent Hackathon:
Track 1 (autonomous trading agent on BSC) and Track 2 (CMC strategy skill).
"""

__version__ = "0.1.0"
