import os
import hashlib
import sqlite3
from pathlib import Path
import pandas as pd
import exifread

class SyncCache:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS synced_files (
                    file_path TEXT PRIMARY KEY,
                    file_size INTEGER,
                    mtime REAL,
                    md5 TEXT,
                    exif_date TEXT,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_file(self, file_path):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT file_size, mtime, md5, exif_date FROM synced_files WHERE file_path = ?", (file_path,))
                return cursor.fetchone()
        except Exception as e:
            print(f"[SyncCache] Fehler beim Lesen aus der Cache-Datenbank: {e}")
            return None

    def save_file(self, file_path, file_size, mtime, md5, exif_date):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO synced_files (file_path, file_size, mtime, md5, exif_date)
                    VALUES (?, ?, ?, ?, ?)
                """, (file_path, file_size, mtime, md5, exif_date))
                conn.commit()
        except Exception as e:
            print(f"[SyncCache] Fehler beim Schreiben in die Cache-Datenbank: {e}")

class SyncManager:
    def __init__(self, ap_client, dry_run=True, db_path=None, allowed_extensions=None):
        self.ap_client = ap_client
        self.dry_run = dry_run
        
        self.allowed_extensions = None
        if allowed_extensions:
            self.allowed_extensions = {ext.lower().lstrip('.') for ext in allowed_extensions}
        
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "sync_cache.db")
        self.cache = SyncCache(db_path)
        
        # Hole existierende MD5 Hashes aus der Amazon Photos Datenbank
        self.existing_md5s = set()
        if self.ap_client and hasattr(self.ap_client, 'db') and 'md5' in self.ap_client.db.columns:
            self.existing_md5s = set(self.ap_client.db.md5.dropna())
            print(f"[SyncManager] Initialisiert. {len(self.existing_md5s)} bekannte Dateien auf Amazon Photos gefunden.")
            if self.allowed_extensions:
                print(f"[SyncManager] Filter für Dateiendungen aktiv: {self.allowed_extensions}")
        else:
            print("[SyncManager] Warnung: Konnte MD5-Hashes nicht aus der Datenbank laden.")

    def calculate_md5(self, file_path: str) -> str:
        """Berechnet den MD5-Hash einer lokalen Datei."""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"[SyncManager] Fehler beim Berechnen des MD5 für {file_path}: {e}")
            return ""

    def get_exif_date(self, file_path: str) -> str:
        """Extrahiert das Aufnahmedatum aus den EXIF-Daten einer Datei."""
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False, stop_tag='DateTimeOriginal')
                # Mögliche EXIF-Tags für Aufnahmedatum
                date_tags = ['EXIF DateTimeOriginal', 'Image DateTime', 'EXIF DateTimeDigitized']
                for tag in date_tags:
                    if tag in tags:
                        val = str(tags[tag])
                        # Erwartetes Format: YYYY:MM:DD HH:MM:SS
                        if len(val) >= 19 and val[4] == ':' and val[7] == ':':
                            normalized = val[:10].replace(':', '-') + ' ' + val[11:19]
                            return normalized
        except Exception as e:
            print(f"[SyncManager] Fehler beim Auslesen der EXIF-Daten für {file_path}: {e}")
        return None

    def find_in_amazon_db(self, filename: str, exif_date: str) -> bool:
        """Prüft, ob eine Datei mit gleichem Namen und Aufnahmedatum in der Amazon DB vorhanden ist."""
        if not self.ap_client or not hasattr(self.ap_client, 'db'):
            return False
        db = self.ap_client.db
        if 'name' not in db.columns or 'contentDate' not in db.columns:
            return False
        
        matches = db[db['name'] == filename]
        if matches.empty:
            return False
            
        if exif_date:
            try:
                exif_ts = pd.to_datetime(exif_date)
                for conn_date in matches['contentDate'].dropna():
                    conn_date_naive = conn_date.tz_localize(None) if hasattr(conn_date, 'tz_localize') else conn_date
                    exif_ts_naive = exif_ts.tz_localize(None) if hasattr(exif_ts, 'tz_localize') else exif_ts
                    if abs((conn_date_naive - exif_ts_naive).total_seconds()) <= 5:
                        return True
            except Exception as e:
                print(f"[SyncManager] Fehler beim Datumsvergleich für {filename}: {e}")
                
        return False

    def process_file(self, file_path: str):
        """Überprüft eine einzelne Datei und gleicht sie mit Amazon Photos ab."""
        if not os.path.isfile(file_path):
            return
            
        # Ignoriere versteckte Dateien
        if os.path.basename(file_path).startswith('.'):
            return

        # Filtere nach Dateiendungen, falls konfiguriert
        if self.allowed_extensions:
            ext = os.path.splitext(file_path)[1].lower().lstrip('.')
            if ext not in self.allowed_extensions:
                return

        filename = os.path.basename(file_path)
        stat = os.stat(file_path)
        file_size = stat.st_size
        mtime = stat.st_mtime
        
        # 1. Stufe: Abgleich mit lokalem SQLite Cache
        cached = self.cache.get_file(file_path)
        if cached:
            cached_size, cached_mtime, cached_md5, cached_exif = cached
            if cached_size == file_size and abs(cached_mtime - mtime) < 1.0:
                print(f"[DRY-RUN/SYNC] Upload nicht notwendig (bereits lokal als synchronisiert markiert): {file_path}")
                return

        file_md5 = self.calculate_md5(file_path)
        if not file_md5:
            return

        exif_date = self.get_exif_date(file_path)
        mode_str = "[DRY-RUN]" if self.dry_run else "[SYNC]"
        
        # 2. Stufe: Abgleich über MD5-Hash aus Amazon DB
        if file_md5 in self.existing_md5s:
            print(f"{mode_str} Upload nicht notwendig (MD5 existiert in Amazon DB): {file_path}")
            if not self.dry_run:
                self.cache.save_file(file_path, file_size, mtime, file_md5, exif_date)
            return

        # 3. Stufe: Abgleich über Name + EXIF-Datum
        if exif_date and self.find_in_amazon_db(filename, exif_date):
            print(f"{mode_str} Upload nicht notwendig (Name + EXIF-Aufnahmedatum '{exif_date}' stimmen überein): {file_path}")
            if not self.dry_run:
                self.cache.save_file(file_path, file_size, mtime, file_md5, exif_date)
            return

        # Check if name exists but metadata/MD5 is different (Warning only)
        if self.ap_client and hasattr(self.ap_client, 'db') and 'name' in self.ap_client.db.columns:
            if filename in self.ap_client.db['name'].values:
                print(f"{mode_str} ACHTUNG: Eine Datei mit dem Namen '{filename}' existiert bereits auf Amazon, aber mit anderem Hash/Datum. Lade hoch: {file_path}")
            else:
                print(f"{mode_str} Neue Datei erkannt, Upload notwendig: {file_path}")
        else:
            print(f"{mode_str} Neue Datei erkannt, Upload notwendig: {file_path}")
            
        if not self.dry_run:
            try:
                with open(file_path, "rb") as f:
                    file_data = f.read()
                
                res = self.ap_client.client.post(
                    self.ap_client.cdproxy_url,
                    content=file_data,
                    params={
                        'name': filename,
                        'kind': 'FILE',
                        'parentNodeId': self.ap_client.root['id'],
                    }
                )
                
                if res.status_code == 409:
                    print(f"[SYNC] Datei existiert bereits auf Amazon (Konflikt): {filename}")
                else:
                    res.raise_for_status()
                    print(f"[SYNC] Erfolgreich hochgeladen: {filename}")
                
                # Speichern im lokalen SQLite Cache und im MD5-Set
                self.cache.save_file(file_path, file_size, mtime, file_md5, exif_date)
                self.existing_md5s.add(file_md5)
            except Exception as e:
                print(f"[SYNC] Fehler beim Hochladen von {filename}: {e}")

    def scan_directory(self, folder_path: str, recursive: bool = True):
        """Scannt ein ganzes Verzeichnis (für den initialen Abgleich)."""
        print(f"[SyncManager] Starte Verzeichnis-Scan: {folder_path} (rekursiv={recursive})")
        if recursive:
            for root, _, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    self.process_file(file_path)
        else:
            try:
                for entry in os.scandir(folder_path):
                    if entry.is_file():
                        self.process_file(entry.path)
            except Exception as e:
                print(f"[SyncManager] Fehler beim Scannen des Verzeichnisses {folder_path}: {e}")
