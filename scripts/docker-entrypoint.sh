#!/usr/bin/env bash
set -e

echo "=========================================================="
echo " Starting ReconAgent API Service Container"
echo "=========================================================="

# 1. Ensure required data and log directories exist
mkdir -p /app/data/uploads
mkdir -p /app/logs

# 2. Wait for PostgreSQL readiness if DATABASE_URL is configured
if [ -n "$DATABASE_URL" ]; then
    echo "Checking PostgreSQL connection ($DATABASE_URL)..."
    python - <<'EOF'
import os
import sys
import time
import psycopg2

db_url = os.getenv("DATABASE_URL")
if not db_url:
    sys.exit(0)

max_retries = 30
for attempt in range(1, max_retries + 1):
    try:
        conn = psycopg2.connect(db_url, connect_timeout=3)
        conn.close()
        print(f"[Entrypoint] Successfully connected to PostgreSQL on attempt {attempt}.")
        sys.exit(0)
    except Exception as exc:
        print(f"[Entrypoint] PostgreSQL not ready yet (attempt {attempt}/{max_retries}): {exc}")
        time.sleep(1)

print("[Entrypoint] ERROR: Timed out waiting for PostgreSQL.")
sys.exit(1)
EOF
fi

echo "PostgreSQL is ready. Launching ReconAgent FastAPI application..."

# 3. Execute requested CMD
exec "$@"
