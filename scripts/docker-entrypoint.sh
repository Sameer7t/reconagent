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

db_url = os.getenv("DATABASE_URL", "")
if not db_url:
    sys.exit(0)

# Normalize postgres:// to postgresql:// for compatibility with Render/Heroku URLs
if db_url.startswith("postgres://"):
    db_url = "postgresql://" + db_url[len("postgres://"):]
    os.environ["DATABASE_URL"] = db_url

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

print("[Entrypoint] WARNING: Could not connect to PostgreSQL within timeout. System will fall back to local SQLite.")
sys.exit(0)
EOF
else
    echo "No DATABASE_URL specified. ReconAgent will use local SQLite persistence."
fi

# 3. Dynamic PORT handling for cloud environments (Render, Railway, Heroku)
PORT_TO_USE="${PORT:-8000}"
echo "Configuring application port: ${PORT_TO_USE}"

if [ "$PORT_TO_USE" != "8000" ]; then
    NEW_ARGS=()
    SKIP_NEXT=0
    for arg in "$@"; do
        if [ "$SKIP_NEXT" -eq 1 ]; then
            NEW_ARGS+=("$PORT_TO_USE")
            SKIP_NEXT=0
        elif [ "$arg" = "--port" ]; then
            NEW_ARGS+=("$arg")
            SKIP_NEXT=1
        else
            NEW_ARGS+=("$arg")
        fi
    done
    set -- "${NEW_ARGS[@]}"
fi

# 4. Execute application
exec "$@"
