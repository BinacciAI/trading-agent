#!/usr/bin/env bash
set -e

# --- TWAK bootstrap (L2) -------------------------------------------------
# Credentials come from env: TWAK_ACCESS_ID / TWAK_HMAC_SECRET (never argv).
if command -v twak >/dev/null 2>&1 && [ -n "$TWAK_ACCESS_ID" ] && [ -n "$TWAK_HMAC_SECRET" ]; then
  if ! twak auth status --json 2>/dev/null | grep -q '"configured": *true'; then
    echo "[entrypoint] twak init (credentials from env)"
    twak init || echo "[entrypoint] twak init failed — venue preflight will report"
  fi
  if [ -n "$TWAK_WALLET_PASSWORD" ]; then
    if ! twak wallet status --json 2>/dev/null | grep -qE '"(exists|configured)": *true|"address"'; then
      echo "[entrypoint] creating agent wallet"
      twak wallet create --password "$TWAK_WALLET_PASSWORD" || echo "[entrypoint] wallet create failed"
    fi
  fi
else
  echo "[entrypoint] TWAK credentials not set — running data/paper layers only"
fi

# --- Agent server (L1 data loop + API + APEX/ERC-8004 when configured) ---
exec uvicorn binacci.chain:create_agent_app --factory --host 0.0.0.0 --port "${PORT:-8000}"
