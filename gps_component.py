"""
gps_component.py
================
קומפוננטה לקבלת GPS מהנייד ב-Streamlit ללא חבילות חיצוניות.

שימוש בלשונית 8:
    from gps_component import render_gps_button, save_store_location

    coords = render_gps_button(key="tab8_gps")
    if coords:
        save_store_location(store_name, coords["lat"], coords["lon"])
"""

import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timezone


# ── קומפוננטת GPS ──────────────────────────────────────────────────────────

GPS_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; padding:4px; font-family: Arial, sans-serif; direction: rtl; }}
    #btn {{
      width: 100%; padding: 10px; font-size: 15px; font-weight: bold;
      background: #1F4E79; color: white; border: none; border-radius: 6px;
      cursor: pointer; direction: rtl;
    }}
    #btn:active {{ background: #163854; }}
    #btn:disabled {{ background: #888; cursor: default; }}
    #status {{ margin-top:6px; font-size:13px; color:#444; text-align:right; }}
    .ok  {{ color: #2E7D32; font-weight: bold; }}
    .err {{ color: #C62828; font-weight: bold; }}
  </style>
</head>
<body>
  <button id="btn" onclick="getGPS()">📍 השתמש במיקום הטלפון שלי</button>
  <div id="status"></div>

<script>
function getGPS() {{
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');

  if (!navigator.geolocation) {{
    status.innerHTML = '<span class="err">❌ הדפדפן לא תומך ב-GPS</span>';
    return;
  }}

  btn.disabled = true;
  btn.textContent = '⏳ מחפש מיקום...';
  status.textContent = 'מבקש הרשאת מיקום...';

  navigator.geolocation.getCurrentPosition(
    function(pos) {{
      const lat = pos.coords.latitude.toFixed(6);
      const lon = pos.coords.longitude.toFixed(6);
      const acc = Math.round(pos.coords.accuracy);

      status.innerHTML = '<span class="ok">✅ מיקום נמצא: ' + lat + ', ' + lon +
                         ' (דיוק ±' + acc + 'מ\')</span>';

      // שלח קואורדינטות לחלון האב (Streamlit iframe)
      window.parent.postMessage({{
        type: 'GPS_COORDS',
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        accuracy: acc
      }}, '*');

      btn.textContent = '✅ מיקום התקבל';
    }},
    function(err) {{
      btn.disabled = false;
      btn.textContent = '📍 השתמש במיקום הטלפון שלי';
      const msgs = {{
        1: '❌ נדחתה הרשאת מיקום — אפשר בהגדרות הדפדפן',
        2: '❌ לא ניתן לאתר מיקום — בדוק GPS',
        3: '❌ פסק זמן — נסה שוב'
      }};
      status.innerHTML = '<span class="err">' + (msgs[err.code] || '❌ שגיאה ' + err.code) + '</span>';
    }},
    {{
      enableHighAccuracy: true,
      timeout: 15000,
      maximumAge: 0
    }}
  );
}}
</script>
</body>
</html>
"""

# ── מאזין postMessage בצד Streamlit ────────────────────────────────────────

LISTENER_HTML = """
<script>
(function() {{
  // מסיר listeners ישנים למניעת כפילויות
  if (window._gpsListenerAttached) return;
  window._gpsListenerAttached = true;

  window.addEventListener('message', function(e) {{
    if (!e.data || e.data.type !== 'GPS_COORDS') return;
    const lat = e.data.lat;
    const lon = e.data.lon;

    // כתוב לתיבות הקלט המוסתרות של Streamlit
    const inputs = window.parent.document.querySelectorAll(
      'input[aria-label="gps_lat_hidden"], input[aria-label="gps_lon_hidden"]'
    );

    // גישה לנייבר של Streamlit דרך query params (מהימן יותר)
    const url = new URL(window.parent.location.href);
    url.searchParams.set('_gps_lat', lat.toFixed(6));
    url.searchParams.set('_gps_lon', lon.toFixed(6));
    url.searchParams.set('_gps_ts',  Date.now());
    window.parent.history.replaceState(null, '', url.toString());

    // גרום ל-Streamlit לרוץ מחדש דרך כפתור מוסתר
    const trigger = window.parent.document.querySelector('[data-testid="gps-trigger-btn"]');
    if (trigger) trigger.click();
  }}, false);
}})();
</script>
"""


def render_gps_button(key: str = "gps") -> dict | None:
    """
    מציג כפתור GPS ומחזיר {'lat': float, 'lon': float} אם נבחר מיקום,
    אחרת None.

    הפעולה:
    1. מציג כפתור HTML שמפעיל navigator.geolocation
    2. קואורדינטות עוברות כ-query params ל-URL
    3. Streamlit קורא אותן בריצה הבאה
    """
    # ── קרא query params מהריצה הקודמת ──
    params = st.query_params
    lat_raw = params.get("_gps_lat")
    lon_raw = params.get("_gps_lon")

    fresh_coords = None
    if lat_raw and lon_raw:
        try:
            fresh_coords = {
                "lat": float(lat_raw),
                "lon": float(lon_raw),
            }
            # נקה params כדי שלא ישפיע על הריצה הבאה
            st.query_params.pop("_gps_lat", None)
            st.query_params.pop("_gps_lon", None)
            st.query_params.pop("_gps_ts",  None)
        except ValueError:
            pass

    # ── הצג קומפוננטת GPS ──
    components.html(GPS_HTML, height=90, scrolling=False)

    # ── מאזין postMessage → query params ──
    components.html(LISTENER_HTML, height=0, scrolling=False)

    # כפתור Streamlit מוסתר שמופעל מ-JS
    # (st.rerun מופעל כאשר ה-query params משתנים ב-Streamlit 1.33+)

    return fresh_coords


# ── שמירת מיקום ב-Supabase ────────────────────────────────────────────────

def save_store_location(store_name: str, city: str,
                        lat: float, lon: float) -> bool:
    """
    מעדכן קואורדינטות חנות ב-Supabase (טבלת stores).
    מחזיר True אם הצליח.
    """
    try:
        from database import db as supabase_db

        result = (
            supabase_db.client
            .table("stores")
            .update({"lat": lat, "lon": lon, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("name", store_name)
            .eq("city", city)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        st.error(f"❌ שגיאה בשמירת מיקום: {e}")
        return False


def save_store_location_github(store_name: str, city: str,
                                lat: float, lon: float,
                                github_token: str, repo: str) -> bool:
    """
    גיבוי: עדכון קואורדינטות ב-stores.csv ב-GitHub.
    משמש כ-fallback אם Supabase לא זמין.
    """
    import base64, csv, io, requests

    api     = f"https://api.github.com/repos/{repo}/contents/stores.csv"
    headers = {"Authorization": f"token {github_token}",
               "Accept": "application/vnd.github.v3+json"}
    try:
        r    = requests.get(api, headers=headers, timeout=10)
        data = r.json()
        sha  = data["sha"]
        text = base64.b64decode(data["content"]).decode("utf-8-sig")

        rows   = list(csv.DictReader(io.StringIO(text)))
        fields = rows[0].keys() if rows else []
        found  = False

        for row in rows:
            if row.get("name") == store_name and row.get("city") == city:
                row["lat"] = str(round(lat, 6))
                row["lon"] = str(round(lon, 6))
                found = True
                break

        if not found:
            return False

        buf = io.StringIO()
        w   = csv.DictWriter(buf, fieldnames=list(fields))
        w.writeheader()
        w.writerows(rows)

        payload = {
            "message": f"fix: GPS {store_name} → {lat},{lon}",
            "content": base64.b64encode(buf.getvalue().encode("utf-8")).decode(),
            "sha": sha,
        }
        res = requests.put(api, headers=headers, json=payload, timeout=15)
        return res.status_code in (200, 201)
    except Exception:
        return False
