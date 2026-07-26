import os
import uuid
import json
import urllib.request
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, abort

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (fine for MVP/testing). For production, swap this for a
# real database (Postgres on Railway is one click away) so data survives
# restarts and you can query history properly.
# ---------------------------------------------------------------------------
CASES = {}
LINK_LIFETIME_MINUTES = 30


def new_case(patient_name=None, phone=None):
    token = uuid.uuid4().hex[:12]
    CASES[token] = {
        "token": token,
        "patient_name": patient_name,
        "phone": phone,
        "created_at": datetime.utcnow(),
        "responded_at": None,
        "status": "pending",  # pending -> located / denied / expired
        # IP geolocation (silent, server-side, no permission prompt)
        "ip_latitude": None,
        "ip_longitude": None,
        "ip_accuracy": None,
        # GPS geolocation (higher accuracy, requires permission prompt)
        "gps_latitude": None,
        "gps_longitude": None,
        "gps_accuracy": None,
        # Best-available coordinates (populated from whichever source arrives)
        "latitude": None,
        "longitude": None,
        "accuracy": None,
        "source": None,  # 'ip' or 'gps'
    }
    return CASES[token]


def is_expired(case):
    return datetime.utcnow() - case["created_at"] > timedelta(minutes=LINK_LIFETIME_MINUTES)


def get_client_ip():
    """Get the real client IP, accounting for reverse proxies (Railway, Nginx, etc.)."""
    # X-Forwarded-For: client_ip, proxy1_ip, proxy2_ip, ...
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    # X-Real-IP (used by some proxies)
    xri = request.headers.get("X-Real-IP")
    if xri:
        return xri.strip()
    return request.remote_addr


def is_private_ip(ip):
    """Check if an IP is private/reserved (can't be geolocated)."""
    if not ip:
        return True
    if ip.startswith(("127.", "10.", "192.168.", "0.", "::1")):
        return True
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (ValueError, IndexError):
            pass
    return False


def ip_geolocate(ip_address):
    """
    Server-side IP geolocation. Returns (lat, lng, accuracy_radius) or (None, None, None).
    Uses ipapi.co as primary, HackMyIP as fallback — both free, HTTPS, no key required.
    """
    if is_private_ip(ip_address):
        return None, None, None

    # ── Primary: ipapi.co (clean top-level JSON fields) ──
    try:
        url = f"https://ipapi.co/{ip_address}/json/"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            lat = data.get("latitude")
            lng = data.get("longitude")
            if lat is not None and lng is not None:
                return float(lat), float(lng), 50000  # ~50km city-level accuracy
    except Exception:
        pass

    # ── Fallback: HackMyIP (may wrap in 'data' key) ──
    try:
        url = f"https://hackmyip.com/api/lookup?ip={ip_address}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode())
            # Some endpoints wrap in 'data', some return top-level
            data = raw.get("data", raw)
            # If there's a nested 'location' dict, try that too
            loc = data if isinstance(data, dict) else {}
            lat = loc.get("latitude")
            lng = loc.get("longitude")
            if lat is None and "location" in loc and isinstance(loc["location"], dict):
                lat = loc["location"].get("latitude")
                lng = loc["location"].get("longitude")
            if lat is not None and lng is not None:
                return float(lat), float(lng), 50000
    except Exception:
        pass

    return None, None, None


# ── Routes ──

@app.route("/")
def index():
    return (
        "Ambulance Locator service is running. "
        "Use POST /create to generate a patient link, or visit /dashboard."
    )


@app.route("/create", methods=["POST"])
def create_case():
    """
    Call this from your dispatch system when a new emergency call comes in.
    Body (JSON, optional): {"patient_name": "...", "phone": "..."}
    Returns: {"token": "...", "link": "https://yourdomain.com/loc/<token>"}
    """
    data = request.get_json(silent=True) or {}
    case = new_case(data.get("patient_name"), data.get("phone"))
    link = request.url_root.rstrip("/") + "/loc/" + case["token"]
    return jsonify({"token": case["token"], "link": link})


@app.route("/loc/<token>")
def location_page(token):
    case = CASES.get(token)
    if not case:
        abort(404)
    if is_expired(case) and case["status"] == "pending":
        case["status"] = "expired"

    # ── Server-side IP geolocation: fires silently, no browser prompt ──
    # Only attempt once per case
    if case["ip_latitude"] is None and case["status"] != "expired":
        client_ip = get_client_ip()
        lat, lng, acc = ip_geolocate(client_ip)
        if lat is not None:
            case["ip_latitude"] = lat
            case["ip_longitude"] = lng
            case["ip_accuracy"] = acc
            # Set as primary (only if GPS hasn't already provided better data)
            if case["gps_latitude"] is None:
                case["latitude"] = lat
                case["longitude"] = lng
                case["accuracy"] = acc
                case["source"] = "ip"
                case["status"] = "located"
                case["responded_at"] = datetime.utcnow()

    return render_template("location.html", token=token, expired=(case["status"] == "expired"))


@app.route("/api/location-update", methods=["POST"])
def location_update():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    case = CASES.get(token)
    if not case:
        return jsonify({"error": "invalid token"}), 404
    if is_expired(case):
        case["status"] = "expired"
        return jsonify({"error": "link expired"}), 410

    source = data.get("source", "gps")
    lat = data.get("latitude")
    lng = data.get("longitude")
    acc = data.get("accuracy")

    if source == "ip":
        case["ip_latitude"] = lat
        case["ip_longitude"] = lng
        case["ip_accuracy"] = acc
        if case["gps_latitude"] is None:
            case["latitude"] = lat
            case["longitude"] = lng
            case["accuracy"] = acc
            case["source"] = "ip"
    else:
        case["gps_latitude"] = lat
        case["gps_longitude"] = lng
        case["gps_accuracy"] = acc
        # GPS always overrides IP as primary
        case["latitude"] = lat
        case["longitude"] = lng
        case["accuracy"] = acc
        case["source"] = "gps"

    if case["status"] == "pending":
        case["status"] = "located"
        case["responded_at"] = datetime.utcnow()

    return jsonify({"ok": True})


@app.route("/api/location-denied", methods=["POST"])
def location_denied():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    case = CASES.get(token)
    if case:
        case["status"] = "denied"
        case["responded_at"] = datetime.utcnow()
    return jsonify({"ok": True})


@app.route("/dashboard")
def dashboard():
    cases = sorted(CASES.values(), key=lambda c: c["created_at"], reverse=True)
    return render_template("dashboard.html", cases=cases)


@app.route("/api/cases")
def api_cases():
    """JSON feed the dashboard polls for live updates."""
    cases = sorted(CASES.values(), key=lambda c: c["created_at"], reverse=True)
    out = []
    for c in cases:
        out.append({
            "token": c["token"],
            "patient_name": c["patient_name"],
            "phone": c["phone"],
            "status": c["status"],
            "source": c["source"],
            # Primary coordinates (best available)
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "accuracy": c["accuracy"],
            # IP geolocation (silent, no prompt)
            "ip_latitude": c["ip_latitude"],
            "ip_longitude": c["ip_longitude"],
            "ip_accuracy": c["ip_accuracy"],
            # GPS geolocation (prompt-based)
            "gps_latitude": c["gps_latitude"],
            "gps_longitude": c["gps_longitude"],
            "gps_accuracy": c["gps_accuracy"],
            "created_at": c["created_at"].isoformat(),
        })
    return jsonify(out)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
