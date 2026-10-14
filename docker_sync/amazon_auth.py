import os
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

def get_config_dir():
    config_dir = "/config" if os.path.exists("/config") else os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
    if not os.path.exists(config_dir):
        config_dir = os.path.dirname(__file__)
    return config_dir

def create_driver():
    """
    Creates and returns a configured Selenium WebDriver instance with a persistent user profile.
    """
    is_docker = os.path.exists('/.dockerenv') or os.environ.get("IS_DOCKER") == "1"
    config_dir = get_config_dir()
    profile_dir = os.path.join(config_dir, "browser_profile")
    os.makedirs(profile_dir, exist_ok=True)

    # Clean up stale Chromium lock files in persistent profile (e.g. after unclean container shutdown)
    for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_path = os.path.join(profile_dir, lock_name)
        if os.path.exists(lock_path) or os.path.islink(lock_path):
            try:
                os.unlink(lock_path)
            except Exception as e:
                print(f"[Auth] Notice: Could not remove stale lock {lock_name}: {e}")

    chrome_options = Options()
    
    # Persistent Chromium profile to preserve device recognition and session tokens
    chrome_options.add_argument(f"--user-data-dir={profile_dir}")
    chrome_options.add_argument("--disk-cache-size=10485760")  # 10MB limit for disk cache
    
    # Generic options
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(f"user-agent={DEFAULT_USER_AGENT}")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=de-DE")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_experimental_option('prefs', {'intl.accept_languages': 'de-DE,de'})
    chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})

    print(f"[Auth] Creating Selenium WebDriver with persistent profile at: {profile_dir}")
    if is_docker:
        print("[Auth] Configuring local headless Chromium inside Docker...")
        chrome_options.add_argument("--headless=new")
        chrome_options.binary_location = "/usr/bin/chromium"
        service = Service(executable_path="/usr/bin/chromedriver")
    else:
        service = Service(ChromeDriverManager().install())
        
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Bypass navigator.webdriver detection
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
    except (AttributeError, Exception):
        pass
    
    return driver

def extract_and_save_cookies(driver, cookie_file):
    """
    Extracts all cookies from the driver and saves them to cookies.json.
    """
    cookies_dict = {}
    cookies = driver.get_cookies()
    for cookie in cookies:
        cookies_dict[cookie['name']] = cookie['value']
    
    if cookies_dict.get('session-id') and (cookies_dict.get('at-acbde') or any(k.startswith('at-') for k in cookies_dict)):
        try:
            with open(cookie_file, "w") as f:
                json.dump(cookies_dict, f)
            print(f"[Auth] Successfully saved {len(cookies_dict)} cookies to {cookie_file}.")
            try:
                from docker_sync.notifications import reset_pushover_marker
                reset_pushover_marker()
            except Exception:
                pass
            return cookies_dict
        except Exception as e:
            print(f"[Auth] Failed to write cookies to file: {e}")
            return cookies_dict
    return None

def get_amazon_cookies(email=None, password=None, force_refresh=False):
    """
    Logs into Amazon.de or silently refreshes the session via persistent Chromium profile.
    """
    config_dir = get_config_dir()
    cookie_file = os.path.join(config_dir, "cookies.json")
    
    if not force_refresh and os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r") as f:
                cookies_dict = json.load(f)
            print("Loaded cookies from cookies.json.")
            return cookies_dict
        except Exception as e:
            print(f"Failed to load cookies from cookies.json: {e}")

    print("Initializing Selenium WebDriver...")
    driver = create_driver()
    cookies_dict = {}

    try:
        print("[Auth] Navigating to Amazon Photos to test existing session / refresh...")
        driver.get("https://www.amazon.de/photos")
        time.sleep(4)

        current_url = driver.current_url
        print(f"[Auth] Current URL: {current_url}")

        # Check if already authenticated via persistent profile
        if "amazon.de/photos" in current_url or "amazon.de/drive" in current_url:
            print("[Auth] Recognized existing browser session on Amazon Photos!")
            saved = extract_and_save_cookies(driver, cookie_file)
            if saved:
                return saved

        # If redirected to signin page, we need credentials
        if not email:
            email = os.environ.get("AMAZON_EMAIL")
        if not password:
            password = os.environ.get("AMAZON_PASSWORD")

        if not email or not password:
            raise ValueError("Amazon session expired and credentials (AMAZON_EMAIL, AMAZON_PASSWORD) are not configured.")

        # Check for Email input field
        try:
            email_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "ap_email"))
            )
            email_input.clear()
            email_input.send_keys(email)
            print("[Auth] Entered email.")

            try:
                continue_btn = driver.find_element(By.ID, "continue")
                continue_btn.click()
                time.sleep(2)
            except Exception:
                pass
        except Exception:
            # Email might already be pre-filled in persistent profile
            pass

        # Wait for password input
        password_input = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.ID, "ap_password"))
        )
        password_input.clear()
        password_input.send_keys(password)
        print("[Auth] Entered password.")

        # Check 'rememberMe' ("Angemeldet bleiben")
        try:
            remember_me = driver.find_element(By.NAME, "rememberMe")
            if not remember_me.is_selected():
                driver.execute_script("arguments[0].click();", remember_me)
                print("[Auth] Checked 'rememberMe' checkbox.")
        except Exception as e:
            print(f"[Auth] Notice: Could not select rememberMe checkbox: {e}")

        # Click sign in
        signin_btn = driver.find_element(By.ID, "signInSubmit")
        signin_btn.click()
        print("[Auth] Submitted sign-in form. Waiting for redirect...")

        # Wait for successful login (redirect to Amazon Photos)
        WebDriverWait(driver, 15).until(
            EC.url_contains("amazon.de/photos")
        )
        time.sleep(3)  # Wait for cookies to settle

        print("[Auth] Login successful. Extracting fresh cookies...")
        saved = extract_and_save_cookies(driver, cookie_file)
        if saved:
            cookies_dict = saved

    except Exception as e:
        print(f"[Auth] Error during get_amazon_cookies: {e}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return cookies_dict

if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()
    cookies = get_amazon_cookies()
    print(f"Retrieved {len(cookies)} cookies.")
