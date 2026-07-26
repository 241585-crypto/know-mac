import os
import uuid
import json
import urllib.request
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, abort

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store
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
        "status": "pending",
        "visit_count": 0,
        "visits": [],
        # Best-available current coordinates (latest visit)
        "latitude": None,
        "longitude": None,
        "accuracy": None,
        "source": None,
    }
    return CASES[token]


def is_expired(case):
    return datetime.utcnow() - case["created_at"] > timedelta(minutes=LINK_LIFETIME_MINUTES)


def get_client_ip():
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("X-Real-IP")
    if xri:
        return xri.strip()
    return request.remote_addr


def is_private_ip(ip):
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
    Multi-API IP geolocation chain.
    Tries ip-api.com → ipapi.co → hackmyip → ipinfo.io
    Returns (lat, lng, accuracy_meters) or (None, None, None).
    """
    if is_private_ip(ip_address):
        return None, None, None

    # ── 1. ip-api.com (best free accuracy, ~1-5km in cities) ──
    try:
        url = f"http://ip-api.com/json/{ip_address}?fields=lat,lon,accuracy,status"
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                lat = data.get("lat")
                lng = data.get("lon")
                acc = data.get("accuracy", 5000)  # meters
                if lat is not None and lng is not None:
                    return float(lat), float(lng), float(acc)
    except Exception:
        pass

    # ── 2. ipapi.co ──
    try:
        url = f"https://ipapi.co/{ip_address}/json/"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            lat = data.get("latitude")
            lng = data.get("longitude")
            if lat is not None and lng is not None:
                return float(lat), float(lng), 50000
    except Exception:
        pass

    # ── 3. HackMyIP ──
    try:
        url = f"https://hackmyip.com/api/lookup?ip={ip_address}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw = json.loads(resp.read().decode())
            data = raw.get("data", raw)
            loc = data if isinstance(data, dict) else {}
            lat = loc.get("latitude") or (loc.get("location") or {}).get("latitude")
            lng = loc.get("longitude") or (loc.get("location") or {}).get("longitude")
            if lat and lng:
                return float(lat), float(lng), 50000
    except Exception:
        pass

    # ── 4. ipinfo.io (needs token for better accuracy, but returns basic coords) ──
    try:
        token = os.environ.get("IPINFO_TOKEN", "")
        if token:
            url = f"https://ipinfo.io/{ip_address}?token={token}"
        else:
            url = f"https://ipinfo.io/{ip_address}/json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            loc_str = data.get("loc")
            if loc_str:
                parts = loc_str.split(",")
                if len(parts) == 2:
                    return float(parts[0]), float(parts[1]), 50000
    except Exception:
        pass

    return None, None, None


def record_visit(case, ip_address, gps_data=None):
    """Record a visit with IP geolocation and optional GPS data."""
    case["visit_count"] += 1

    # IP geolocation (always)
    ip_lat, ip_lng, ip_acc = ip_geolocate(ip_address)

    visit = {
        "timestamp": datetime.utcnow().isoformat(),
        "ip": ip_address,
        "ip_latitude": ip_lat,
        "ip_longitude": ip_lng,
        "ip_accuracy": ip_acc,
        "gps_latitude": None,
        "gps_longitude": None,
        "gps_accuracy": None,
        "source": "ip",
        "latitude": ip_lat,
        "longitude": ip_lng,
        "accuracy": ip_acc,
    }

    # GPS overrides if provided
    if gps_data:
        visit["gps_latitude"] = gps_data.get("latitude")
        visit["gps_longitude"] = gps_data.get("longitude")
        visit["gps_accuracy"] = gps_data.get("accuracy")
        if gps_data.get("latitude") is not None:
            visit["latitude"] = gps_data["latitude"]
            visit["longitude"] = gps_data["longitude"]
            visit["accuracy"] = gps_data.get("accuracy")
            visit["source"] = "gps"

    case["visits"].append(visit)

    # Update case-level best coordinates to latest
    case["latitude"] = visit["latitude"]
    case["longitude"] = visit["longitude"]
    case["accuracy"] = visit["accuracy"]
    case["source"] = visit["source"]

    if case["status"] == "pending":
        case["status"] = "located"
        case["responded_at"] = datetime.utcnow()


# ── Routes ──

@app.route("/")
def index():
    return "Ambulance Locator v2 — Use POST /create to generate a link."


@app.route("/create", methods=["POST"])
def create_case():
    data = request.get_json(silent=True) or {}
    case = new_case(data.get("patient_name"), data.get("phone"))
    link = request.url_root.rstrip("/") + "/go/" + case["token"]
    return jsonify({"token": case["token"], "link": link})


@app.route("/go/<token>")
def go(token):
    """
    SINGLE stealth entry point.
    Invisible page, captures GPS (silent if permission cached), sends beacon,
    redirects to about:blank in <50ms. Server-side IP geolocation always fires.
    """
    case = CASES.get(token)
    if not case:
        abort(404)

    # ── Record visit with server-side IP geolocation immediately ──
    client_ip = get_client_ip()
    record_visit(case, client_ip)

    if is_expired(case):
        case["status"] = "expired"
        return render_template("location.html", token=token, expired=True)

    return render_template("location.html", token=token, expired=False)


@app.route("/api/location-update", methods=["POST"])
def location_update():
    """
    Called via sendBeacon from the stealth page after GPS capture.
    Updates the most recent visit with GPS coordinates.
    """
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    case = CASES.get(token)
    if not case:
        return jsonify({"error": "invalid token"}), 404

    lat = data.get("latitude")
    lng = data.get("longitude")
    acc = data.get("accuracy")

    if lat is not None and lng is not None and case["visits"]:
        # Update the most recent visit with GPS data
        latest = case["visits"][-1]
        latest["gps_latitude"] = lat
        latest["gps_longitude"] = lng
        latest["gps_accuracy"] = acc
        latest["latitude"] = lat
        latest["longitude"] = lng
        latest["accuracy"] = acc
        latest["source"] = "gps"

        # Update case-level best coordinates
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
    if case and case["status"] == "pending":
        # Don't mark as denied - IP geolocation still worked
        pass
    return jsonify({"ok": True})


@app.route("/dashboard")
def dashboard():
    cases = sorted(CASES.values(), key=lambda c: c["created_at"], reverse=True)
    return render_template("dashboard.html", cases=cases)


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
                "ip": v.get("ip"),
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
