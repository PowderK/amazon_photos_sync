import os
import tempfile
from flask import Flask, render_template, request, flash, redirect, url_for
from werkzeug.utils import secure_filename
import sys

# Add parent dir to path to import amazon_photos if needed, though pip install installed it
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amazon_photos import AmazonPhotos
from docker_sync.amazon_auth import get_amazon_cookies

app = Flask(__name__)
app.secret_key = "super_secret_key_for_flash_messages"

# Global instance for AmazonPhotos
ap_client = None

import time

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

@app.route("/login", methods=["GET", "POST"])
def login():
    global ap_client
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        try:
            init_amazon_photos(email=email, password=password)
            flash("Erfolgreich eingeloggt!")
            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Fehler beim Login: {str(e)}")
            return redirect(url_for("login"))
    return render_template("login.html")

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
