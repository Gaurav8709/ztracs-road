#!/usr/bin/env bash
# ==============================================================================
# Z-TRACS Road Intelligence Platform — 24/7 Background Runner
# Runs FastAPI server continuously in background (nohup mode).
# Closing SSH / EC2 Terminal will NOT stop the server.
# ==============================================================================
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ -f .env ]; then
    sed -i 's/ADMIN_PASSWORD=change-me-admin-password/ADMIN_PASSWORD=admin123/g' .env 2>/dev/null || true
    set -a
    source .env
    set +a
fi

if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Kill any existing background uvicorn server instances
pkill -f "uvicorn backend.main:app" 2>/dev/null || true

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "=========================================================="
echo "  Z-TRACS Road Intelligence — 24/7 Background Service"
echo "=========================================================="
echo "Starting backend server in background..."
nohup python3 -m uvicorn backend.main:app --host "$HOST" --port "$PORT" > app.log 2>&1 &

PID=$!
sleep 2

if ps -p $PID > /dev/null; then
    echo "✅ Z-TRACS Server is running 24/7 in background (PID: $PID)."
    echo "📄 Logs: tail -f app.log"
    echo "🌐 URL:  http://3.109.28.196:8000"
    echo "Closing terminal window will NOT stop this server!"
else
    echo "❌ Server failed to start. Check app.log:"
    cat app.log
fi
