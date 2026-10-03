#!/usr/bin/env bash
# Z-TRACS Road Intelligence - Frontend Server (Split Mode)
# Serves frontend static assets on port 3000 with configurable API_BASE

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

PORT="${PORT:-3000}"
HOST="${HOST:-0.0.0.0}"
API_BASE="${API_BASE:-http://3.109.28.196:8000}"


echo "=========================================================="
echo "  Z-TRACS Road Intelligence Platform - Frontend Server"
echo "  Theme 02 — AI for Roads, Bridges & Tunnels (Split Mode)"
echo "=========================================================="
echo ""
echo "🚀 Serving frontend assets on http://${HOST}:${PORT}/"
echo "API requests will route to API_BASE: ${API_BASE}"
echo "Press Ctrl+C to stop."
echo ""

# Prefer virtualenv python if activated/present, else python3
PYTHON_BIN="python3"
if [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
elif [ -x "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
fi

export API_BASE
export PORT
export HOST

exec "$PYTHON_BIN" -c "
import http.server
import os
import sys

API_BASE = os.getenv('API_BASE', 'http://127.0.0.1:8000')
PORT = int(os.getenv('PORT', '3000'))
HOST = os.getenv('HOST', '127.0.0.1')
FRONTEND_DIR = os.path.abspath(os.path.join(os.getcwd(), 'frontend'))

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def do_GET(self):
        clean_path = self.path.split('?')[0].rstrip('/')
        if clean_path in ('/js/config.js', '/config.js'):
            config_file = os.path.join(FRONTEND_DIR, 'js', 'config.js')
            with open(config_file, 'r', encoding='utf-8') as f:
                orig_cfg = f.read()
            content = f'window.API_BASE = \"{API_BASE}\";\n' + orig_cfg
            encoded = content.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        return super().do_GET()

server = http.server.HTTPServer((HOST, PORT), CustomHandler)
server.serve_forever()
"
