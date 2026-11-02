import shutil
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VECTOR_DB = ROOT / "data" / "vector_db"
BACKUP_DIR = ROOT / "backups"

if not VECTOR_DB.exists():
    print("Nothing to backup: vector_db does not exist.")
    exit(0)

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
dest = BACKUP_DIR / f"vector_db_{ts}"

shutil.copytree(VECTOR_DB, dest)
size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
print(f"Backup saved: {dest}")
print(f"Size: {size / 1024:.1f} KB ({size} bytes)")
