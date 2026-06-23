#!/bin/bash
set -e

CONFIG_DIR="/config"
COOKIE_FILE="${CONFIG_DIR}/cookies.json"

# Check if config dir exists, if not create it
if [ ! -d "$CONFIG_DIR" ]; then
    echo "[Entrypoint] Warning: /config directory not mounted. Using local directories."
    CONFIG_DIR="/app/docker_sync"
    COOKIE_FILE="${CONFIG_DIR}/cookies.json"
fi

echo "[Entrypoint] Checking for cookies at ${COOKIE_FILE}..."

if [ ! -f "$COOKIE_FILE" ]; then
    echo "[Entrypoint] No cookies found. Starting Flask Login Web App on port 5000..."
    echo "[Entrypoint] Please open http://localhost:5000 in your browser to log in."
    
    # Start the Flask app in the background
    python -c "import sys; sys.path.append('/app'); from docker_sync.web_app import app; app.run(host='0.0.0.0', port=5000)" &
    WEB_APP_PID=$!
    
    echo "[Entrypoint] Web App started with PID $WEB_APP_PID. Waiting for login..."
    
    # Wait for cookies.json to be created by the login flow
    while [ ! -f "$COOKIE_FILE" ]; do
        sleep 2
    done
    
    echo "[Entrypoint] cookies.json detected! Stopping Web App..."
    kill $WEB_APP_PID
    wait $WEB_APP_PID 2>/dev/null || true
    echo "[Entrypoint] Web App stopped."
fi

echo "[Entrypoint] Starting folder watcher..."
# Execute folder_watcher.py
exec python docker_sync/folder_watcher.py
