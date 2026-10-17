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

COOKIES_VALID=false

if [ -f "$COOKIE_FILE" ]; then
    echo "[Entrypoint] Validating existing cookies.json..."
    if python -c "
import sys, os, json
sys.path.append('/app')
try:
    with open('${COOKIE_FILE}', 'r') as f:
        cookies = json.load(f)
    
    from amazon_photos import AmazonPhotos
    ap = AmazonPhotos(cookies=cookies, skip_folders=True)
    print('[Entrypoint] Cookies are valid and verified with AmazonPhotos!')
    try:
        from docker_sync.notifications import reset_pushover_marker
        reset_pushover_marker()
    except Exception:
        pass
    sys.exit(0)
except Exception as e:
    print(f'[Entrypoint] Cookie validation failed: {e}')
    sys.exit(1)
"; then
        COOKIES_VALID=true
    fi
fi

# If cookies are not valid, attempt silent refresh / auto-login using the persistent browser profile
if [ "$COOKIES_VALID" = false ]; then
    echo "[Entrypoint] Attempting session refresh/auto-login via persistent browser profile..."
    if python -c "
import sys, os
sys.path.append('/app')
from docker_sync.amazon_auth import get_amazon_cookies
try:
    cookies = get_amazon_cookies(os.environ.get('AMAZON_EMAIL'), os.environ.get('AMAZON_PASSWORD'), force_refresh=True)
    if cookies and 'session-id' in cookies:
        print('[Entrypoint] Successfully refreshed session via persistent browser profile!')
        sys.exit(0)
except Exception as e:
    print(f'[Entrypoint] Silent refresh / auto-login failed: {e}')
sys.exit(1)
"; then
        COOKIES_VALID=true
    fi
fi

# If still not valid, manual verification via Web UI is required
if [ "$COOKIES_VALID" = false ]; then
    echo "[Entrypoint] Session expired or requires verification. Deleting stale cookies.json..."
    rm -f "$COOKIE_FILE"
    
    # Notify user via Pushover if configured
    python -c "
import sys
sys.path.append('/app')
try:
    from docker_sync.notifications import send_pushover_notification
    send_pushover_notification('Amazon Photos session expired. Please open Web UI on port 5000/5001 to verify.', title='Amazon Photos Sync Alert')
except Exception as pe:
    print(f'[Entrypoint] Failed to send Pushover alert: {pe}')
" || true

    echo "[Entrypoint] Starting Flask Login Web App on port 5000..."
    echo "[Entrypoint] Please open http://localhost:5000 in your browser to log in."
    
    python -c "import sys; sys.path.append('/app'); from docker_sync.web_app import app; app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)"
    echo "[Entrypoint] Web App stopped. Proceeding..."
fi

echo "[Entrypoint] Starting folder watcher..."
exec python docker_sync/folder_watcher.py
