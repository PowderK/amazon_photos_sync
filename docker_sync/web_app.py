import os
import tempfile
import sys
import json
import time
import signal
import threading
from flask import Flask, render_template, request, flash, redirect, url_for
from werkzeug.utils import secure_filename

# Add parent dir to path to import amazon_photos if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amazon_photos import AmazonPhotos
from docker_sync.amazon_auth import get_amazon_cookies, create_driver

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def shutdown_server():
    time.sleep(1.5)  # Let the response send completely
    print("[Web App] Self-terminating after successful login...")
    os.kill(os.getpid(), signal.SIGINT)

def trigger_shutdown():
    threading.Thread(target=shutdown_server).start()

app = Flask(__name__)
app.secret_key = "super_secret_key_for_flash_messages"

# Global instance for AmazonPhotos
ap_client = None

# Global Selenium active session state
selenium_session = {
    'driver': None,
    'status': 'idle',  # 'idle', 'need_captcha', 'need_otp', 'failed'
    'screenshot': None,
    'error': None,
    'password': None
}

def init_amazon_photos(email=None, password=None):
    global ap_client
    if ap_client is None:
        print(f"[{time.strftime('%H:%M:%S')}] Initializing Amazon Photos Client...")
        t0 = time.time()
        cookies = get_amazon_cookies(email=email, password=password)
        print(f"[{time.strftime('%H:%M:%S')}] Cookies retrieved after {time.time() - t0:.2f} seconds.")
        if not cookies or 'session-id' not in cookies:
            raise Exception("Failed to retrieve valid cookies from Amazon.")
        
        t1 = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] Instantiating AmazonPhotos class (fast init without folders)...")
        ap_client = AmazonPhotos(cookies=cookies, skip_folders=True)
        print(f"[{time.strftime('%H:%M:%S')}] Amazon Photos Client class initialized after {time.time() - t1:.2f} seconds.")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] Using existing Amazon Photos Client.")
    return ap_client

def parse_and_save_cookies(cookies_str):
    try:
        data = json.loads(cookies_str.strip())
        cookies_dict = {}
        if isinstance(data, list):
            for item in data:
                name = item.get("name")
                value = item.get("value")
                if name in ["session-id", "ubid-acbde", "at-acbde"]:
                    cookies_dict[name] = value
        elif isinstance(data, dict):
            for name in ["session-id", "ubid-acbde", "at-acbde"]:
                if name in data:
                    cookies_dict[name] = data[name]
        
        # Verify we got the essential cookies
        if not cookies_dict.get("session-id") or not cookies_dict.get("at-acbde"):
            raise ValueError("Required cookies (session-id, at-acbde) are missing.")
            
        config_dir = "/config" if os.path.exists("/config") else os.path.dirname(__file__)
        cookie_file = os.path.join(config_dir, "cookies.json")
        with open(cookie_file, "w") as f:
            json.dump(cookies_dict, f)
        return True
    except Exception as e:
        print(f"Error parsing cookies: {e}")
        return False

def evaluate_page_state(driver):
    global selenium_session, ap_client
    current_url = driver.current_url
    print(f"[Web UI Login] Current URL: {current_url}")
    try:
        print(f"[Web UI Login] Page Title: {driver.title}")
        body_text = driver.find_element(By.TAG_NAME, "body").text
        print(f"[Web UI Login] Page text snippet: {body_text[:500].replace(chr(10), ' | ')}")
    except Exception as e:
        print(f"[Web UI Login] Could not read page text/title: {e}")
    
    # Check if redirect to photos/drive was successful
    if "amazon.de/photos" in current_url or "amazon.de/drive" in current_url:
        cookies_dict = {}
        cookies = driver.get_cookies()
        for cookie in cookies:
            if cookie['name'] in ['at-acbde', 'ubid-acbde', 'session-id']:
                cookies_dict[cookie['name']] = cookie['value']
        
        if cookies_dict.get('session-id') and cookies_dict.get('at-acbde'):
            config_dir = "/config" if os.path.exists("/config") else os.path.dirname(__file__)
            cookie_file = os.path.join(config_dir, "cookies.json")
            with open(cookie_file, "w") as f:
                json.dump(cookies_dict, f)
            print("[Web UI Login] Cookies successfully saved.")
            
            # Pre-initialize client
            ap_client = AmazonPhotos(cookies=cookies_dict, skip_folders=True)
            
            try:
                driver.quit()
            except Exception:
                pass
            selenium_session['driver'] = None
            selenium_session['status'] = 'success'
            trigger_shutdown()
            return render_template("success.html")

    # Check for OTP page
    try:
        driver.find_element(By.ID, "auth-mfa-otpcode")
        selenium_session['status'] = 'need_otp'
        selenium_session['screenshot'] = driver.get_screenshot_as_base64()
        return render_template("login.html", session=selenium_session)
    except Exception:
        pass

    # Check for Captcha
    try:
        driver.find_element(By.ID, "auth-captcha-image")
        selenium_session['status'] = 'need_captcha'
        selenium_session['screenshot'] = driver.get_screenshot_as_base64()
        return render_template("login.html", session=selenium_session)
    except Exception:
        pass

    # Check for general login error
    error_message = None
    try:
        error_box = driver.find_element(By.ID, "auth-error-message-box")
        error_message = error_box.text
        selenium_session['error'] = error_message
    except Exception:
        selenium_session['error'] = None

    if error_message:
        selenium_session['status'] = 'failed'
        selenium_session['screenshot'] = driver.get_screenshot_as_base64()
        try:
            driver.quit()
        except Exception:
            pass
        selenium_session['driver'] = None
        return render_template("login.html", session=selenium_session)

    # Default fallback: keep driver alive for user action (like push notifications)
    selenium_session['status'] = 'need_action'
    selenium_session['screenshot'] = driver.get_screenshot_as_base64()
    return render_template("login.html", session=selenium_session)

@app.route("/login", methods=["GET", "POST"])
def login():
    global selenium_session
    
    if request.method == "GET":
        # Reset any stale driver
        if selenium_session['driver']:
            try:
                selenium_session['driver'].quit()
            except Exception:
                pass
            selenium_session['driver'] = None
        selenium_session['status'] = 'idle'
        selenium_session['screenshot'] = None
        selenium_session['error'] = None
        selenium_session['password'] = None
        return render_template("login.html", session=selenium_session)
        
    # POST handling
    action = request.form.get("action")
    
    # 1. Option B: Direct Cookie Paste
    if action == "import_cookies":
        cookies_json = request.form.get("cookies_json")
        if cookies_json and parse_and_save_cookies(cookies_json):
            trigger_shutdown()
            return render_template("success.html")
        else:
            flash("Fehler: Ungültiges Cookie-Format. Bitte überprüfe die Daten.")
            return redirect(url_for("login"))
            
    # 2. Option A: Initial email/password submit
    elif action == "submit_credentials":
        email = request.form.get("email")
        password = request.form.get("password")
        selenium_session['password'] = password  # Save password to re-enter if captcha prompts
        
        print("[Web UI Login] Starting Selenium flow...")
        driver = create_driver()
        selenium_session['driver'] = driver
        
        try:
            driver.get("https://www.amazon.de/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.de%2Fphotos&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=amzn_photos_web_de&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0")
            
            # Step 1: Input Email
            email_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ap_email"))
            )
            email_input.clear()
            email_input.send_keys(email)
            
            try:
                driver.find_element(By.ID, "continue").click()
            except Exception:
                pass
                
            time.sleep(3) # Wait for page transition
            
            # Check if a Captcha image exists on the page immediately after clicking continue (Email-page Captcha)
            try:
                driver.find_element(By.ID, "auth-captcha-image")
                print("[Web UI Login] Captcha triggered on Email page.")
                selenium_session['status'] = 'need_captcha'
                selenium_session['screenshot'] = driver.get_screenshot_as_base64()
                return render_template("login.html", session=selenium_session)
            except Exception:
                pass
                
            # Step 2: Input Password (wait until visible)
            password_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ap_password"))
            )
            password_input.clear()
            password_input.send_keys(password)
            
            # Submit Credentials
            driver.find_element(By.ID, "signInSubmit").click()
            time.sleep(5)
            
            return evaluate_page_state(driver)
            
        except Exception as e:
            print(f"[Web UI Login] Error during credentials submit: {e}")
            selenium_session['status'] = 'failed'
            try:
                selenium_session['error'] = str(e)
                selenium_session['screenshot'] = driver.get_screenshot_as_base64()
                driver.quit()
            except Exception:
                pass
            selenium_session['driver'] = None
            return render_template("login.html", session=selenium_session)
            
    # 3. Submit Captcha Code
    elif action == "submit_captcha":
        captcha_code = request.form.get("captcha_code")
        driver = selenium_session['driver']
        if not driver:
            flash("Sitzung abgelaufen. Bitte erneut anmelden.")
            return redirect(url_for("login"))
            
        try:
            captcha_input = driver.find_element(By.ID, "ap_captcha_guess")
            captcha_input.clear()
            captcha_input.send_keys(captcha_code)
            
            # Check if password field is visible right now (Password-page Captcha)
            password_field_present = False
            try:
                password_input = driver.find_element(By.ID, "ap_password")
                password_field_present = True
                if selenium_session['password']:
                    password_input.clear()
                    password_input.send_keys(selenium_session['password'])
            except Exception:
                pass
                
            # Click continue or submit
            try:
                if not password_field_present:
                    driver.find_element(By.ID, "continue").click()
                else:
                    driver.find_element(By.ID, "signInSubmit").click()
            except Exception:
                driver.find_element(By.ID, "signInSubmit").click()
                
            time.sleep(3)
            
            # If we were on the Email page and just solved Captcha, we should now be on the Password page.
            if not password_field_present:
                # Wait for password input to appear and fill it
                try:
                    password_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.ID, "ap_password"))
                    )
                    if selenium_session['password']:
                        password_input.clear()
                        password_input.send_keys(selenium_session['password'])
                    driver.find_element(By.ID, "signInSubmit").click()
                    time.sleep(5)
                except Exception:
                    pass # Let evaluate_page_state handle it
            
            return evaluate_page_state(driver)
        except Exception as e:
            print(f"[Web UI Login] Error during captcha submit: {e}")
            selenium_session['status'] = 'failed'
            try:
                selenium_session['error'] = str(e)
                selenium_session['screenshot'] = driver.get_screenshot_as_base64()
                driver.quit()
            except Exception:
                pass
            selenium_session['driver'] = None
            return render_template("login.html", session=selenium_session)
            
    # 4. Submit OTP / 2FA Code
    elif action == "submit_otp":
        otp_code = request.form.get("otp_code")
        driver = selenium_session['driver']
        if not driver:
            flash("Sitzung abgelaufen. Bitte erneut anmelden.")
            return redirect(url_for("login"))
            
        try:
            otp_input = driver.find_element(By.ID, "auth-mfa-otpcode")
            otp_input.clear()
            otp_input.send_keys(otp_code)
            
            # Submit OTP
            try:
                driver.find_element(By.ID, "auth-signin-button").click()
            except Exception:
                try:
                    driver.find_element(By.ID, "signInSubmit").click()
                except Exception:
                    pass
                
            time.sleep(5)
            
            return evaluate_page_state(driver)
        except Exception as e:
            print(f"[Web UI Login] Error during OTP submit: {e}")
            selenium_session['status'] = 'failed'
            try:
                selenium_session['error'] = str(e)
                selenium_session['screenshot'] = driver.get_screenshot_as_base64()
                driver.quit()
            except Exception:
                pass
            selenium_session['driver'] = None
            return render_template("login.html", session=selenium_session)

    # 5. Check Status (for push notifications / manual action confirmation)
    elif action == "check_status":
        driver = selenium_session['driver']
        if not driver:
            flash("Sitzung abgelaufen. Bitte erneut anmelden.")
            return redirect(url_for("login"))
            
        try:
            return evaluate_page_state(driver)
        except Exception as e:
            print(f"[Web UI Login] Error checking status: {e}")
            selenium_session['status'] = 'failed'
            try:
                selenium_session['error'] = str(e)
                selenium_session['screenshot'] = driver.get_screenshot_as_base64()
                driver.quit()
            except Exception:
                pass
            selenium_session['driver'] = None
            return render_template("login.html", session=selenium_session)

    return render_template("login.html", session=selenium_session)

@app.route("/", methods=["GET", "POST"])
def index():
    global ap_client
    if ap_client is None:
        return redirect(url_for("login"))
        
    if request.method == "POST":
        if 'photo' not in request.files:
            flash("Keine Datei ausgewählt")
            return redirect(request.url)
        
        file = request.files['photo']
        if file.filename == '':
            flash("Keine Datei ausgewählt")
            return redirect(request.url)
        
        if file:
            filename = secure_filename(file.filename)
            # Speichern in temporärem Ordner
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, filename)
            file.save(file_path)
            
            try:
                # Amazon Photos Client (sollte bereits in /login initialisiert worden sein)
                client = ap_client
                if client is None:
                    return redirect(url_for('login'))
                
                # Datei hochladen
                print(f"Uploading file: {file_path}")
                # client.upload(file_path) # Funktioniert nur für Verzeichnisse
                
                with open(file_path, "rb") as f:
                    file_data = f.read()
                
                res = client.client.post(
                    client.cdproxy_url,
                    content=file_data,
                    params={
                        'name': filename,
                        'kind': 'FILE',
                        'parentNodeId': client.root['id'],
                    }
                )
                
                if res.status_code == 409:
                    flash(f"Datei '{filename}' existiert bereits auf Amazon Photos (Konflikt).")
                else:
                    res.raise_for_status()
                    flash(f"Datei '{filename}' wurde erfolgreich hochgeladen!")
            except Exception as e:
                flash(f"Fehler beim Hochladen: {str(e)}")
            finally:
                # Temporäre Datei löschen
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
            return redirect(url_for('index'))
            
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
