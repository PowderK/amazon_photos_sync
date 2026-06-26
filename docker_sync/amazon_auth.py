import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import json

def create_driver():
    """
    Creates and returns a configured Selenium WebDriver instance.
    """
    is_docker = os.path.exists('/.dockerenv') or os.environ.get("IS_DOCKER") == "1"
    
    chrome_options = Options()
    
    # Generic options
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--lang=de-DE")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_experimental_option('prefs', {'intl.accept_languages': 'de-DE,de'})
    chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})

    print("[Auth] Creating local Selenium WebDriver...")
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

def get_amazon_cookies(email=None, password=None, force_refresh=False):
    """
    Logs into Amazon.de and retrieves the necessary cookies for Amazon Photos.
    """
    config_dir = "/config" if os.path.exists("/config") else os.path.dirname(__file__)
    cookie_file = os.path.join(config_dir, "cookies.json")
    
    if not force_refresh and os.path.exists(cookie_file):
        try:
            with open(cookie_file, "r") as f:
                cookies_dict = json.load(f)
            print("Loaded cookies from cookies.json.")
            return cookies_dict
        except Exception as e:
            print(f"Failed to load cookies from cookies.json: {e}")

    if not email:
        email = os.environ.get("AMAZON_EMAIL")
    if not password:
        password = os.environ.get("AMAZON_PASSWORD")

    if not email or not password:
        raise ValueError("Amazon email and password must be provided via arguments or environment variables.")

    print("Initializing Selenium WebDriver...")
    driver = create_driver()

    cookies_dict = {}

    try:
        print("Navigating to Amazon Login...")
        # Navigate to Amazon login page directly or Amazon Photos
        driver.get("https://www.amazon.de/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.de%2Fphotos&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=amzn_photos_web_de&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")

        # Wait for email input
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "ap_email"))
        )
        email_input.send_keys(email)
        
        # Click continue if it exists (sometimes it asks for email then password on next page)
        try:
            continue_btn = driver.find_element(By.ID, "continue")
            continue_btn.click()
        except Exception:
            pass
        
        # Wait for password input
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "ap_password"))
        )
        password_input.send_keys(password)
        
        # Click sign in
        signin_btn = driver.find_element(By.ID, "signInSubmit")
        signin_btn.click()

        # Wait for successful login (redirect to Amazon Photos)
        print("Waiting for login to complete...")
        WebDriverWait(driver, 15).until(
            EC.url_contains("amazon.de/photos")
        )
        time.sleep(3) # Wait a bit for cookies to settle

        print("Login successful. Extracting cookies...")
        # Extrahiere die benötigten Cookies
        cookies = driver.get_cookies()
        for cookie in cookies:
            if cookie['name'] in ['at-acbde', 'ubid-acbde', 'session-id']:
                cookies_dict[cookie['name']] = cookie['value']

        print(f"Extracted cookies: {list(cookies_dict.keys())}")
        
        # Speichere die Cookies für die zukünftige Nutzung
        if cookies_dict:
            try:
                with open(cookie_file, "w") as f:
                    json.dump(cookies_dict, f)
                print("Cookies saved to cookies.json.")
            except Exception as e:
                print(f"Failed to save cookies: {e}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        driver.quit()

    return cookies_dict

if __name__ == "__main__":
    # Test script locally
    import dotenv
    dotenv.load_dotenv()
    cookies = get_amazon_cookies()
    print(f"Retrieved cookies: {cookies}")
