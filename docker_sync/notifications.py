import os
import time

def send_pushover_notification(message: str, title: str = "Amazon Photos Sync", rate_limit: bool = True) -> bool:
    """
    Sends a Pushover notification if the environment variables are set.
    If rate_limit is True, it will only send one notification until the token is updated/validated again
    (tracked via a marker file).
    """
    token = os.environ.get("PUSHOVER_TOKEN") or os.environ.get("PUSHOVER_APP_TOKEN")
    user = os.environ.get("PUSHOVER_USER") or os.environ.get("PUSHOVER_USER_KEY")
    
    if not token or not user:
        print("[Pushover] Not configured. Set PUSHOVER_TOKEN and PUSHOVER_USER to enable alerts.")
        return False
        
    config_dir = "/config" if os.path.exists("/config") else os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
    # Fallback to local directory if config_dir is not writable or does not exist
    if not os.path.exists(config_dir):
        config_dir = os.path.dirname(__file__)
        
    marker_file = os.path.join(config_dir, "pushover_sent.marker")
    
    if rate_limit and os.path.exists(marker_file):
        print("[Pushover] Notification skipped (rate-limiting: marker file exists).")
        return False
        
    try:
        import requests
        url = "https://api.pushover.net/1/messages.json"
        data = {
            "token": token,
            "user": user,
            "message": message,
            "title": title
        }
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        
        if rate_limit:
            try:
                with open(marker_file, "w") as f:
                    f.write(str(time.time()))
                print(f"[Pushover] Created marker file at: {marker_file}")
            except Exception as e:
                print(f"[Pushover] Warning: Could not create marker file: {e}")
                
        print("[Pushover] Notification sent successfully.")
        return True
    except Exception as e:
        print(f"[Pushover] Failed to send notification: {e}")
        return False

def reset_pushover_marker():
    """Removes the marker file so a new notification can be sent if the token becomes invalid again."""
    config_dir = "/config" if os.path.exists("/config") else os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
    if not os.path.exists(config_dir):
        config_dir = os.path.dirname(__file__)
        
    marker_file = os.path.join(config_dir, "pushover_sent.marker")
    if os.path.exists(marker_file):
        try:
            os.remove(marker_file)
            print("[Pushover] Reset notification marker (new cookies/token generated or validated).")
        except Exception as e:
            print(f"[Pushover] Warning: Could not remove marker file: {e}")
