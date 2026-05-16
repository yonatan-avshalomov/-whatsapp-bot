"""
kml_exporter.py
===============
מייצא את כל החנויות לקובץ KML לייבוא ב"המפות שלי" של Google.

שימוש:
    from kml_exporter import build_kml
    kml_bytes = build_kml(stores, visit_stats)

ייבוא ב-Google My Maps:
    1. maps.google.com → "המפות שלי" → "צור מפה חדשה"
    2. "ייבא" → העלה את הקובץ → בחר עמודת שם
    3. כל הסניפים מופיעים עם צבעים לפי רשת
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime


# ── צבעי רשתות (פורמט KML: AABBGGRR) ─────────────────────
CHAIN_STYLES = {
    "שילב":  {"color": "ffE05C1F", "icon": "http://maps.google.com/mapfiles/kml/paddle/blu-circle.png"},
    "מכבי":  {"color": "ff27A818", "icon": "http://maps.google.com/mapfiles/kml/paddle/grn-circle.png"},
    "ניצת":  {"color": "ff1478FF", "icon": "http://maps.google.com/mapfiles/kml/paddle/ylw-circle.png"},
    "פרטי":  {"color": "ff888888", "icon": "http://maps.google.com/mapfiles/kml/paddle/wht-circle.png"},
}

def _chain_key(chain: str) -> str:
    """מחזיר מפתח סגנון לפי שם הרשת."""
    if "שילב" in (chain or ""):  return "שילב"
    if "מכבי" in (chain or ""):  return "מכבי"
    if "ניצת" in (chain or "") or "הדובדבן" in (chain or ""): return "ניצת"
    return "פרטי"

def _safe_float(v, default=0.0) -> float:
    try:
        f = float(v)
        return f if f != 0.0 else default
    except (ValueError, TypeError):
        return default

def _html_desc(store: dict, vstats: dict) -> str:
    """בונה תיאור HTML לבועת המידע של הסמן."""
    parts = []
    if store.get("address"):
        parts.append(f"📍 {store['address']}, {store.get('city','')}")
    if store.get("phone"):
        parts.append(f"📞 {store['phone']}")
    if store.get("chain"):
        parts.append(f"🏷️ {store['chain']}")

    days = vstats.get("days_since")
    last = vstats.get("last_date_str", "—")
    if days is not None:
        if days <= 14:   icon = "🟢"
        elif days <= 30: icon = "🟡"
        elif days <= 45: icon = "🟠"
        else:            icon = "🔴"
        parts.append(f"{icon} ביקור אחרון: {last} (לפני {days} ימים)")
    else:
        parts.append("⚫ לא בוקר")

    return "<br>".join(parts)


def build_kml(stores: list[dict],
              visit_stats: dict | None = None) -> bytes:
    """
    בונה קובץ KML מלא מרשימת החנויות.

    Parameters
    ----------
    stores      : list[dict]  רשימת חנויות עם lat, lon, name, city, chain...
    visit_stats : dict | None  תוצאות get_all_visit_stats (אופציונלי)

    Returns
    -------
    bytes  — תוכן קובץ KML מוכן לשמירה / הורדה
    """
    vstats_map = visit_stats or {}

    # ── מסמך ─────────────────────────────────────────────
    kml  = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc  = ET.SubElement(kml, "Document")

    name_el = ET.SubElement(doc, "name")
    name_el.text = f"חנויות — {datetime.now().strftime('%d/%m/%Y')}"

    desc_el = ET.SubElement(doc, "description")
    desc_el.text = f"{len(stores)} חנויות | מעודכן {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    # ── סגנונות לפי רשת ──────────────────────────────────
    for chain_key, style in CHAIN_STYLES.items():
        s = ET.SubElement(doc, "Style", id=f"style_{chain_key}")
        icon_style = ET.SubElement(s, "IconStyle")
        color_el   = ET.SubElement(icon_style, "color")
        color_el.text = style["color"]
        scale_el   = ET.SubElement(icon_style, "scale")
        scale_el.text  = "1.1"
        icon_el    = ET.SubElement(icon_style, "Icon")
        href_el    = ET.SubElement(icon_el, "href")
        href_el.text   = style["icon"]

        label_style = ET.SubElement(s, "LabelStyle")
        lscale = ET.SubElement(label_style, "scale")
        lscale.text = "0.8"

    # ── תיקיות לפי רשת ───────────────────────────────────
    folders: dict[str, ET.Element] = {}
    chain_counts: dict[str, int]   = {}

    for chain_key in CHAIN_STYLES:
        folder = ET.SubElement(doc, "Folder")
        fname  = ET.SubElement(folder, "name")
        fname.text = chain_key
        folders[chain_key] = folder
        chain_counts[chain_key] = 0

    # ── סמנים ────────────────────────────────────────────
    skipped = 0
    for s in stores:
        lat = _safe_float(s.get("lat"), 0.0)
        lon = _safe_float(s.get("lon"), 0.0)

        if lat == 0.0 or lon == 0.0:
            skipped += 1
            continue

        chain_key = _chain_key(s.get("chain", ""))
        folder    = folders[chain_key]
        vstats    = vstats_map.get(s.get("name", ""), {})

        pm   = ET.SubElement(folder, "Placemark")

        # שם
        pname = ET.SubElement(pm, "name")
        pname.text = s.get("name", "")

        # תיאור
        pdesc = ET.SubElement(pm, "description")
        pdesc.text = _html_desc(s, vstats)

        # סגנון
        style_url = ET.SubElement(pm, "styleUrl")
        style_url.text = f"#style_{chain_key}"

        # קואורדינטות
        point = ET.SubElement(pm, "Point")
        coords = ET.SubElement(point, "coordinates")
        coords.text = f"{lon},{lat},0"

        chain_counts[chain_key] += 1

    # ── עדכן שמות תיקיות עם מספרים ──────────────────────
    for chain_key, folder in folders.items():
        fname = folder.find("name")
        if fname is not None:
            fname.text = f"{chain_key} ({chain_counts[chain_key]})"

    # ── המר ל-bytes ───────────────────────────────────────
    raw    = ET.tostring(kml, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")
    return pretty


def build_kml_filename() -> str:
    """שם קובץ עם תאריך."""
    return f"stores_{datetime.now().strftime('%Y%m%d')}.kml"


# ── הרצה ישירה (בדיקה) ────────────────────────────────────
if __name__ == "__main__":
    import sys, csv, io, requests
    sys.stdout.reconfigure(encoding="utf-8")

    BASE = "https://raw.githubusercontent.com/yonatan-avshalomov/-whatsapp-bot/main"
    r    = requests.get(f"{BASE}/stores.csv", timeout=15)
    stores = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))

    kml_bytes = build_kml(stores)

    out = f"stores_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.kml"
    with open(out, "wb") as f:
        f.write(kml_bytes)

    print(f"✅ נשמר: {out} ({len(kml_bytes):,} bytes)")
    print(f"   חנויות: {len(stores)}")
