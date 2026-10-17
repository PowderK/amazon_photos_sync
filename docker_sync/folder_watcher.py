import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from sync_manager import SyncManager

class PhotoFolderHandler(FileSystemEventHandler):
    def __init__(self, sync_manager: SyncManager):
        self.sync_manager = sync_manager

    def on_created(self, event):
        if not event.is_directory:
            print(f"[Watcher] Neues Element erkannt: {event.src_path}")
            # Kurze Wartezeit, um sicherzugehen, dass die Datei vollständig geschrieben wurde
            time.sleep(1)
            self.sync_manager.process_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            print(f"[Watcher] Modifiziertes Element erkannt: {event.src_path}")
            time.sleep(1)
            self.sync_manager.process_file(event.src_path)

def start_watcher(folder_path: str, sync_manager: SyncManager, recursive: bool = True, skip_initial_scan: bool = False):
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"[Watcher] Ordner {folder_path} erstellt.")

    print(f"[Watcher] Starte Überwachung für Ordner: {folder_path} (rekursiv={recursive})")
    
    # Initialer Abgleich aller bereits vorhandenen Dateien
    if not skip_initial_scan:
        sync_manager.scan_directory(folder_path, recursive=recursive)
    else:
        print("[Watcher] Initialer Verzeichnis-Scan übersprungen (SKIP_INITIAL_SCAN aktiv).")

    event_handler = PhotoFolderHandler(sync_manager)
    observer = Observer()
    observer.schedule(event_handler, folder_path, recursive=recursive)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[Watcher] Überwachung gestoppt.")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    import argparse
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from amazon_auth import get_amazon_cookies
    from amazon_photos import AmazonPhotos

    parser = argparse.ArgumentParser(description="Amazon Photos Folder Watcher Sync")
    parser.add_argument(
        "--watch-dir", "-w",
        default=os.environ.get("WATCH_DIR", "./sync_test_folder"),
        help="Verzeichnis, das überwacht werden soll (Standard: ./sync_test_folder oder env WATCH_DIR)"
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        default=os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes"),
        help="Führt einen Probelauf durch, ohne Dateien hochzuladen"
    )
    parser.add_argument(
        "--extensions", "-e",
        nargs="*",
        default=os.environ.get("SYNC_EXTENSIONS", "").split() if os.environ.get("SYNC_EXTENSIONS") else None,
        help="Liste von erlaubten Dateiendungen (z.B. heic jpg png). Standardmäßig werden alle Dateien synchronisiert."
    )
    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        default=os.environ.get("SYNC_RECURSIVE", "true").lower() in ("true", "1", "yes"),
        help="Überwacht das Verzeichnis rekursiv inklusive aller Unterverzeichnisse (Standard: True)"
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Deaktiviert die rekursive Überwachung von Unterverzeichnissen"
    )
    parser.add_argument(
        "--skip-initial-scan",
        action="store_true",
        default=os.environ.get("SKIP_INITIAL_SCAN", "false").lower() in ("true", "1", "yes"),
        help="Überspringt den initialen Verzeichnis-Scan beim Start und überwacht nur neue/geänderte Dateien (Standard: False oder env SKIP_INITIAL_SCAN)"
    )
    args = parser.parse_args()

    cookies = get_amazon_cookies()
    if cookies:
        config_dir = "/config" if os.path.exists("/config") else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
        if not os.path.exists(config_dir):
            config_dir = os.path.dirname(os.path.abspath(__file__))
        ap_db_path = os.path.join(config_dir, "ap.parquet")
        sync_cache_path = os.path.join(config_dir, "sync_cache.db")

        print(f"Initialisiere AmazonPhotos Client (Katalog: {ap_db_path})...")
        client = AmazonPhotos(cookies=cookies, db_path=ap_db_path, skip_folders=True)
        
        mode_str = "DRY-RUN" if args.dry_run else "LIVE-SYNC"
        print(f"Modus: {mode_str}")
        print(f"Überwachtes Verzeichnis: {args.watch_dir}")
        print(f"Rekursive Überwachung: {args.recursive}")
        print(f"Initialer Scan überspringen: {args.skip_initial_scan}")
        if args.extensions:
            print(f"Erlaubte Dateiendungen: {args.extensions}")
        
        sync_mgr = SyncManager(client, dry_run=args.dry_run, db_path=sync_cache_path, allowed_extensions=args.extensions)
        start_watcher(args.watch_dir, sync_mgr, recursive=args.recursive, skip_initial_scan=args.skip_initial_scan)
    else:
        print("Keine Cookies gefunden. Bitte zuerst über die Web-App einloggen oder Umgebungsvariablen setzen.")
