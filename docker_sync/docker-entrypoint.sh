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

if [ -f "$COOKIE_FILE" ]; then
    echo "[Entrypoint] Validating existing cookies.json..."
    if ! python -c "
import sys, os, json, requests
try:
    with open('${COOKIE_FILE}', 'r') as f:
        cookies = json.load(f)
    
    headers = {
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'x-amzn-sessionid': cookies.get('session-id', ''),
    }
    
    # Determine TLD
    tld = 'de'
    for k in cookies:
        if k.endswith('_main'):
            tld = 'com'
            break
        elif k.startswith('at-acb'):
            tld = k.split('at-acb')[-1]
            break
            
    r = requests.get(f'https://www.amazon.{tld}/drive/v1/account/usage', headers=headers, cookies=cookies, timeout=10)
    if r.status_code == 401:
        print('[Entrypoint] Existing cookies are expired (401).')
        sys.exit(1)
        
    r.raise_for_status()
    print('[Entrypoint] Cookies are valid.')
    sys.exit(0)
except Exception as e:
    print(f'[Entrypoint] Cookie validation failed: {e}')
    sys.exit(1)
"; then
        echo "[Entrypoint] Deleting invalid/expired cookies.json..."
        rm -f "$COOKIE_FILE"
    fi
fi

if [ ! -f "$COOKIE_FILE" ]; then
    if [ -n "$AMAZON_EMAIL" ] && [ -n "$AMAZON_PASSWORD" ]; then
        echo "[Entrypoint] Found AMAZON_EMAIL and AMAZON_PASSWORD env variables. Attempting automatic login..."
        if python -c "
import sys, os
sys.path.append('/app')
from docker_sync.amazon_auth import get_amazon_cookies
try:
    cookies = get_amazon_cookies(os.environ.get('AMAZON_EMAIL'), os.environ.get('AMAZON_PASSWORD'), force_refresh=True)
    if cookies and 'session-id' in cookies:
        sys.exit(0)
except Exception as e:
    print(f'[Entrypoint] Auto-login error: {e}')
sys.exit(1)
"; then
            echo "[Entrypoint] Automatic login successful! cookies.json saved."
        else
            echo "[Entrypoint] Automatic login failed (likely due to Captcha/2FA). Falling back to Web UI..."
        fi
    fi
fi

if [ ! -f "$COOKIE_FILE" ]; then
    echo "[Entrypoint] No cookies found. Starting Flask Login Web App on port 5000..."
    echo "[Entrypoint] Please open http://localhost:5000 in your browser to log in."
    
    # Run the Flask app in the foreground. It will self-terminate upon successful login.
    python -c "import sys; sys.path.append('/app'); from docker_sync.web_app import app; app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)"
    
    echo "[Entrypoint] Web App stopped. Proceeding..."
fi

echo "[Entrypoint] Starting folder watcher..."
# Execute folder_watcher.py
exec python docker_sync/folder_watcher.py
