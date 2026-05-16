"""
batch_geocode_google.py
=======================
סקריפט חד-פעמי (ואפשר להריץ שוב) לעדכון קואורדינטות כל החנויות ב-stores.csv
באמצעות Google Maps Geocoding API.

מצבי הרצה:
  python batch_geocode_google.py              # מגאוקד רק חנויות ללא GPS
  python batch_geocode_google.py --all        # מגאוקד מחדש את כולן (force)
  python batch_geocode_google.py --dry-run    # מדפיס בלבד, לא שומר
"""

import csv, sys, argparse, shutil
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

# ── ייבוא המודול המרכזי ───────────────────────────────────────────────────────
from geocoder import geocode_batch

STORES_FILE  = Path(__file__).parent / "stores.csv"
BACKUP_DIR   = Path(__file__).parent / "backups"

def backup_csv():
    """שומר גיבוי לפני שינויים."""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"stores_{ts}.csv"
    shutil.copy2(STORES_FILE, dst)
    print(f"📦 גיבוי נשמר: {dst.name}")
    return dst

def main():
    parser = argparse.ArgumentParser(description="Geocode all stores with Google Maps")
    parser.add_argument("--all",     action="store_true", help="גאוקד מחדש את כולן (כולל עם GPS קיים)")
    parser.add_argument("--dry-run", action="store_true", help="הצג תוצאות בלי לשמור")
    args = parser.parse_args()

    # ── טען CSV ──
    with open(STORES_FILE, encoding="utf-8-sig") as f:
        reader    = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        stores    = list(reader)

    print(f"📂 {len(stores)} חנויות טעונות מ-stores.csv")
    print(f"🔧 מצב: {'force כולן' if args.all else 'רק חסרי GPS'}")
    if args.dry_run:
        print("🏃 DRY RUN — לא יישמר כלום\n")
    print("=" * 60)

    # ── הוסף עמודת formatted_address אם לא קיימת ──
    if "formatted_address" not in fieldnames:
        fieldnames.append("formatted_address")
        for s in stores:
            s.setdefault("formatted_address", "")

    # ── הרץ Batch Geocoding ──
    force = args.all
    updated, skipped, failed = geocode_batch(
        stores,
        force=force,
        skip_with_coords=not force
    )

    print("\n" + "=" * 60)
    print(f"✅ עודכנו:  {updated}")
    print(f"⏭️  דולגו:   {skipped}")
    print(f"❌ נכשלו:   {failed}")
    print(f"📊 סה\"כ:    {len(stores)}")

    if args.dry_run:
        print("\n⚠️  DRY RUN — לא נשמר.")
        return

    if updated == 0:
        print("\nאין שינויים לשמור.")
        return

    # ── גיבוי ──
    backup_csv()

    # ── שמור CSV מעודכן ──
    with open(STORES_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(stores)

    print(f"\n💾 stores.csv עודכן — {updated} קואורדינטות חדשות")
    print("📌 הרץ: git add stores.csv && git commit -m 'עדכון GPS Google Maps' && git push")

if __name__ == "__main__":
    main()
