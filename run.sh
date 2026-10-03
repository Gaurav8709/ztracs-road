#!/usr/bin/env bash
# Z-TRACS Road Intelligence Launch Script
# Rodic InfraAI Innovation Challenge 2026 - Theme 02

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=========================================================="
echo "  Z-TRACS Road Intelligence Platform"
echo "  Theme 02 — AI for Roads, Bridges & Tunnels"
echo "=========================================================="

# Check Python version (Verified: Python 3.9.6; Python 3.10–3.13 are NOT VERIFIED on host)
PYTHON_CMD="python3"
if [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON_CMD="$VIRTUAL_ENV/bin/python"
elif [ -x "venv/bin/python" ]; then
    PYTHON_CMD="venv/bin/python"
fi

if ! command -v "$PYTHON_CMD" &> /dev/null || ! "$PYTHON_CMD" -c 'import sys; sys.exit(0 if (3, 9) <= sys.version_info < (3, 14) else 1)' 2>/dev/null; then
    FOUND_SUPPORTED=""
    for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 /usr/bin/python3; do
        if command -v "$candidate" &> /dev/null && "$candidate" -c 'import sys; sys.exit(0 if (3, 9) <= sys.version_info < (3, 14) else 1)' 2>/dev/null; then
            PYTHON_CMD="$candidate"
            FOUND_SUPPORTED="1"
            break
        fi
    done
    if [ "$FOUND_SUPPORTED" != "1" ]; then
        DETECTED_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || echo "unknown")
        echo "❌ Error: Python $DETECTED_VER detected. Z-TRACS requires Python 3.9 through 3.13 (Verified: 3.9.6; 3.10–3.13 NOT VERIFIED)."
        echo "Please install a supported Python version (Verified on 3.9.6; 3.10–3.13 NOT VERIFIED)."
        exit 1
    fi
fi

echo "Using Python: $($PYTHON_CMD --version) (Verified: Python 3.9.6; 3.10–3.13 NOT VERIFIED)"

# Check for .env file; offer to copy .env.example if missing (Item B2 / 2.3)
if [ ! -f .env ]; then
    echo "⚠️  Notice: .env configuration file not found."
    if [ -f .env.example ]; then
        echo "A configuration template (.env.example) is available."
        if [ -t 0 ]; then
            read -p "Would you like to copy .env.example to .env now? [Y/n] " response
            case "$response" in
                [nN][oO]|[nN])
                    echo "Please configure .env before starting Z-TRACS."
                    exit 1
                    ;;
                *)
                    cp .env.example .env
                    echo "✅ Copied .env.example to .env."
                    ;;
            esac
        else
            cp .env.example .env
            echo "✅ Non-interactive mode: copied .env.example to .env."
        fi
    else
        echo "❌ Error: Neither .env nor .env.example was found."
        exit 1
    fi
fi

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    "$PYTHON_CMD" -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt

export PYTHONPATH="$DIR"

# Pre-flight database connectivity check (Item B1 / 2.2)
echo "Checking PostgreSQL database connectivity..."
if ! python3 -c "
import os, sys, psycopg
from urllib.parse import urlsplit
db_url = os.getenv('DATABASE_URL', '')
if not db_url:
    print('ERROR: DATABASE_URL is not configured.', file=sys.stderr)
    sys.exit(1)
try:
    with psycopg.connect(db_url, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1;')
except Exception:
    try:
        parts = urlsplit(db_url)
        host = parts.hostname or 'localhost'
        port = parts.port or 5432
        dbname = parts.path.lstrip('/').split('?')[0] if parts.path else 'unknown'
        target_info = f'host={host}, port={port}, database={dbname}'
    except Exception:
        target_info = 'host=unknown, port=unknown, database=unknown'
    print(f'ERROR: Cannot connect to database ({target_info}): Connection failed. (Credentials masked)', file=sys.stderr)
    sys.exit(1)
"; then
    echo ""
    echo "❌ Error: Database is unreachable."
    echo "Please ensure your PostgreSQL/PostGIS database is running."
    echo "If running locally with Docker, run:"
    echo "    docker compose up -d"
    echo ""
    exit 1
fi
echo "✅ Database is reachable."

# Note: Demo dataset is seeded on-demand by the application lifespan hook (backend/main.py)
# Duplicate external seeding invocation removed per Item B3 (2.4).

HOST="${HOST:-0.0.0.0}"

PORT="${PORT:-8000}"
RELOAD_FLAG=""
if [ "${DEV}" = "1" ]; then
    RELOAD_FLAG="--reload"
fi

echo ""
echo "🚀 Starting Z-TRACS Server on http://${HOST}:${PORT}..."
echo "Open http://${HOST}:${PORT} in your browser to access the platform."
echo "Press Ctrl+C to stop."
echo ""

uvicorn backend.main:app --host "$HOST" --port "$PORT" $RELOAD_FLAG
