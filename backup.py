"""Safe backup of hospital.db (works while the app is running).

Creates backups/hospital_YYYY-MM-DD_HHMM.db and keeps only the newest KEEP files.
Run it daily with Windows Task Scheduler (see README).
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_FILE = Path("hospital.db")
BACKUP_DIR = Path("backups")
KEEP = 30


def main():
    if not DB_FILE.exists():
        raise SystemExit("hospital.db not found. Run this from the project folder.")
    BACKUP_DIR.mkdir(exist_ok=True)
    target = BACKUP_DIR / f"hospital_{datetime.now():%Y-%m-%d_%H%M}.db"

    source = sqlite3.connect(DB_FILE)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    backups = sorted(BACKUP_DIR.glob("hospital_*.db"))
    for old in backups[:-KEEP]:
        old.unlink()
    print(f"Backup saved: {target} ({len(backups[-KEEP:])} kept)")


if __name__ == "__main__":
    main()
