FROM python:3.12-slim

# Node.js 20 + Trust Wallet Agent Kit CLI (L2: self-custody execution)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @trustwallet/cli \
    && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Agent package (fastapi + uvicorn are core deps)
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir "bnbagent[server,ipfs]" || echo "bnbagent optional install failed — APEX/ERC-8004 disabled"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
CMD ["/entrypoint.sh"]
