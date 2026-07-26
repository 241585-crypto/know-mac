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

# ═══════════════════════════════════════════════════════════════════
# COMPLETE PAKISTAN MOBILE PREFIX DATABASE
# ═══════════════════════════════════════════════════════════════════
# Based on:
# - Wikipedia (Telephone numbers in Pakistan)
# - PTA National Numbering Plan
# - PakSimLookUp / operator databases
# - Industry knowledge
#
# Operator Key:
#   MNC 01 = Jazz (Mobilink heritage)
#   MNC 07 = Jazz (Warid heritage, merged)
#   MNC 04 = Zong (CMPak / China Mobile)
#   MNC 03 = Ufone (PTCL)
#   MNC 06 = Telenor Pakistan
#   MNC 05 = SCOM (Special Comms Org, AJK/GB only)
# ═══════════════════════════════════════════════════════════════════

# ── Complete MNC Mapping: prefix → (mnc, operator_name) ──
# Covers all allocated Pakistani mobile prefixes 0300-0399

PAKISTAN_PREFIX_MAP = {
    # ── Jazz (Mobilink heritage) — MNC 01 ──
    "300": ("01", "Jazz"), "301": ("01", "Jazz"), "302": ("01", "Jazz"),
    "303": ("01", "Jazz"), "304": ("01", "Jazz"), "305": ("01", "Jazz"),
    "306": ("01", "Jazz"), "307": ("01", "Jazz"), "308": ("01", "Jazz"),
    "309": ("01", "Jazz"),

    # ── Zong (CMPak / China Mobile) — MNC 04 ──
    "310": ("04", "Zong"), "311": ("04", "Zong"), "312": ("04", "Zong"),
    "313": ("04", "Zong"), "314": ("04", "Zong"), "315": ("04", "Zong"),
    "316": ("04", "Zong"), "317": ("04", "Zong"), "318": ("04", "Zong"),
    "319": ("04", "Zong"),

    # ── Jazz (Warid heritage, merged into Jazz) — MNC 07 ──
    "320": ("07", "Jazz"), "321": ("07", "Jazz"), "322": ("07", "Jazz"),
    "323": ("07", "Jazz"), "324": ("07", "Jazz"), "325": ("07", "Jazz"),
    "326": ("07", "Jazz"), "327": ("07", "Jazz"), "328": ("07", "Jazz"),
    "329": ("07", "Jazz"),

    # ── Ufone (PTCL) — MNC 03 ──
    "330": ("03", "Ufone"), "331": ("03", "Ufone"), "332": ("03", "Ufone"),
    "333": ("03", "Ufone"), "334": ("03", "Ufone"), "335": ("03", "Ufone"),
    "336": ("03", "Ufone"), "337": ("03", "Ufone"), "338": ("03", "Ufone"),
    "339": ("03", "Ufone"),

    # ── Telenor Pakistan — MNC 06 ──
    "340": ("06", "Telenor"), "341": ("06", "Telenor"), "342": ("06", "Telenor"),
    "343": ("06", "Telenor"), "344": ("06", "Telenor"), "345": ("06", "Telenor"),
    "346": ("06", "Telenor"), "347": ("06", "Telenor"), "348": ("06", "Telenor"),
    "349": ("06", "Telenor"),

    # ── Unallocated / Reserved ──
    # 350-354: No active allocation
    "350": (None, None), "351": (None, None), "352": (None, None),
    "353": (None, None), "354": (None, None),

    # ── SCOM (Special Comms Org — AJK & Gilgit-Baltistan only) — MNC 05 ──
    "355": ("05", "SCOM"), "356": ("05", "SCOM"), "357": ("05", "SCOM"),

    # ── Unallocated ──
    "358": (None, None), "359": (None, None),

    # ── Zong (CMPak — newer allocation) — MNC 04 ──
    "360": ("04", "Zong"), "361": ("04", "Zong"), "362": ("04", "Zong"),
    "363": ("04", "Zong"), "364": ("04", "Zong"), "365": ("04", "Zong"),

    # ── Unallocated ──
    "366": (None, None), "367": (None, None), "368": (None, None),
    "369": (None, None),

    # ── Zong (newer allocation: 370, 371) — MNC 04 ──
    "370": ("04", "Zong"), "371": ("04", "Zong"),

    # ── Jazz (newer allocation: 372-379) — MNC 01 ──
    "372": ("01", "Jazz"), "373": ("01", "Jazz"), "374": ("01", "Jazz"),
    "375": ("01", "Jazz"), "376": ("01", "Jazz"), "377": ("01", "Jazz"),
    "378": ("01", "Jazz"), "379": ("01", "Jazz"),

    # ── Future / Reserved (380-399) ──
    # These may be allocated in the future — map to None for now
    "380": (None, None), "381": (None, None), "382": (None, None),
    "383": (None, None), "384": (None, None), "385": (None, None),
    "386": (None, None), "387": (None, None), "388": (None, None),
    "389": (None, None),
    "390": (None, None), "391": (None, None), "392": (None, None),
    "393": (None, None), "394": (None, None), "395": (None, None),
    "396": (None, None), "397": (None, None), "398": (None, None),
    "399": (None, None),
}


# ── City Prefix Mapping (HEURISTIC — based on general distribution patterns) ──
# IMPORTANT: Mobile prefix-to-city is NOT an exact science in Pakistan.
# SIMs are sold nationwide regardless of prefix. This mapping is based on
# general distribution trends and SHOULD NOT be treated as definitive.
# It improves accuracy when IP geolocation completely fails (shows wrong country)
# but is less reliable than IP + carrier + timezone validation.

PAKISTAN_CITY_PREFIX_MAP = {
    # ── Jazz (030x) — largest network, nation-wide ──
    "300": "Lahore", "301": "Lahore", "302": "Lahore", "303": "Lahore",
    "304": "Faisalabad", "305": "Faisalabad",
    "306": "Multan", "307": "Multan", "308": "Multan", "309": "Multan",

    # ── Zong (031x) — strong in Punjab, Karachi, Islamabad ──
    "310": "Islamabad", "311": "Islamabad", "312": "Karachi", "313": "Karachi",
    "314": "Lahore", "315": "Lahore", "316": "Faisalabad", "317": "Faisalabad",
    "318": "Multan", "319": "Hyderabad",

    # ── Jazz/Warid (032x) — nation-wide, strong in Sindh ──
    "320": "Karachi", "321": "Karachi", "322": "Karachi", "323": "Karachi",
    "324": "Karachi", "325": "Karachi",
    "326": "Hyderabad", "327": "Hyderabad",
    "328": "Sukkur", "329": "Sukkur",

    # ── Ufone (033x) — nation-wide, strong in twin cities ──
    "330": "Islamabad", "331": "Islamabad", "332": "Rawalpindi", "333": "Islamabad",
    "334": "Lahore", "335": "Lahore",
    "336": "Islamabad", "337": "Lahore",
    "338": "Lahore", "339": "Faisalabad",

    # ── Telenor (034x) — nation-wide, strong in north ──
    "340": "Islamabad", "341": "Islamabad", "342": "Rawalpindi", "343": "Rawalpindi",
    "344": "Lahore", "345": "Lahore", "346": "Lahore", "347": "Lahore",
    "348": "Faisalabad", "349": "Faisalabad",

    # ── Unallocated (0350-0354) ──
    "350": "Islamabad", "351": "Islamabad", "352": "Lahore", "353": "Karachi", "354": "Karachi",

    # ── SCOM (0355-0357) — Azad Kashmir & Gilgit-Baltistan ONLY ──
    "355": "Muzaffarabad", "356": "Gilgit", "357": "Skardu",

    # ── Unallocated (0358-0359) ──
    "358": "Peshawar", "359": "Peshawar",

    # ── Zong new (0360-0365) ──
    "360": "Karachi", "361": "Karachi", "362": "Lahore", "363": "Lahore",
    "364": "Islamabad", "365": "Islamabad",

    # ── Unallocated (0366-0369) ──
    "366": "Multan", "367": "Faisalabad", "368": "Peshawar", "369": "Quetta",

    # ── Zong new (0370-0371) ──
    "370": "Karachi", "371": "Lahore",

    # ── Jazz new (0372-0379) ──
    "372": "Lahore", "373": "Lahore", "374": "Lahore",
    "375": "Karachi", "376": "Karachi", "377": "Karachi",
    "378": "Islamabad", "379": "Islamabad",

    # ── Future (0380-0399) — assume major cities ──
    "380": "Karachi", "381": "Karachi", "382": "Lahore", "383": "Lahore",
    "384": "Islamabad", "385": "Islamabad", "386": "Faisalabad", "387": "Faisalabad",
    "388": "Multan", "389": "Multan",
    "390": "Peshawar", "391": "Peshawar", "392": "Quetta", "393": "Quetta",
    "394": "Hyderabad", "395": "Hyderabad", "396": "Sukkur", "397": "Gujranwala",
    "398": "Sialkot", "399": "Sialkot",
}


# ── Complete City Coordinates for Pakistan ──
# Includes all major cities, divisional headquarters, and districts
# Used as last-resort fallback when ALL geolocation methods fail

PAKISTAN_CITY_COORDS = {
    # ── Provincial Capitals & Major Metros ──
    "Karachi":       (24.8607, 67.0011),    # Sindh capital, largest city
    "Lahore":        (31.5204, 74.3587),    # Punjab capital
    "Islamabad":     (33.6844, 73.0479),    # Federal capital
    "Rawalpindi":    (33.5651, 73.0169),    # Twin city of Islamabad
    "Faisalabad":    (31.4504, 73.1350),    # Punjab — industrial hub
    "Multan":        (30.1575, 71.5249),    # South Punjab
    "Peshawar":      (34.0150, 71.5249),    # KPK capital
    "Quetta":        (30.1798, 66.9750),    # Balochistan capital
    "Hyderabad":     (25.3960, 68.3578),    # Sindh
    "Muzaffarabad":  (34.3700, 73.4712),    # AJK capital
    "Gilgit":        (35.9200, 74.3100),    # Gilgit-Baltistan capital
    "Skardu":        (35.3000, 75.6300),    # GB

    # ── Major Punjab Cities ──
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
    "Mardan":        (34.2000, 72.0400),
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

    # ── Sindh Cities ──
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

    # ── KPK Cities ──
    "Abbottabad":    (34.1500, 73.2200),
    "Swat (Mingora)":(34.7800, 72.3600),
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

    # ── Balochistan Cities ──
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

    # ── AJK Cities ──
    "Mirpur (AJK)":  (33.1500, 73.7500),
    "Kotli":         (33.5200, 73.9100),
    "Rawalakot":     (33.8600, 73.7600),
    "Bhimber":       (33.0100, 74.0700),
    "Palandri":      (33.7200, 73.6800),
    "Bagh":          (33.9800, 73.7800),
    "Hattian Bala":  (34.1700, 73.7400),
    "Neelum":        (34.5900, 73.9100),
    "Hajira":        (33.7100, 73.7900),

    # ── Gilgit-Baltistan Cities ──
    "Hunza":         (36.3200, 74.6600),
    "Nagar":         (36.2700, 74.7200),
    "Ghanche":       (35.8500, 76.4000),
    "Astore":        (35.3600, 74.8600),
    "Diamer":        (35.5600, 74.2400),
    "Ghizer":        (36.2400, 73.2500),
    "Shigar":        (35.4200, 75.7300),
    "Kharmang":      (35.2400, 75.9900),

    # ── FATA / Merged Districts ──
    "Kurram":        (33.8700, 70.0800),
    "Khyber":        (34.1000, 71.0800),
    "Orakzai":       (33.8300, 70.9200),
    "Mohmand":       (34.4100, 71.3700),
    "Bajaur":        (34.6900, 71.5000),
    "North Waziristan":(32.9800, 70.1500),
    "South Waziristan":(32.2000, 69.5000),
    "FR Bannu":      (32.8300, 70.2900),
    "FR Dera Ismail Khan":(31.7800, 70.3800),
    "FR Kohat":      (33.3800, 71.1700),
    "FR Lakki":      (32.4300, 70.7100),
    "FR Peshawar":   (34.0100, 71.4200),
    "FR Tank":       (32.3200, 70.1900),
}


def parse_phone_number(phone):
    """Parse Pakistani phone number with complete prefix coverage.
    
    Returns (country_code, prefix_3, mcc, mnc, operator_name, city_hint).
    Covers all allocated prefixes from 0300 to 0399.
    """
    if not phone:
        return None, None, None, None, None, None

    digits = re.sub(r"\D", "", phone)
    
    # Handle Pakistan numbers: +92XXXXXXXXX or 03XXXXXXXXX
    is_pakistan = False
    prefix = None
    
    if digits.startswith("92") and len(digits) == 12:
        is_pakistan = True
        prefix = digits[2:5]  # e.g., "300", "310"
    elif digits.startswith("0") and len(digits) == 11:
        is_pakistan = True
        prefix = digits[1:4]  # e.g., "300", "310"
    
    if is_pakistan and prefix:
        mcc = "410"  # Pakistan Mobile Country Code
        
        # Look up MNC and operator
        prefix_data = PAKISTAN_PREFIX_MAP.get(prefix)
        if prefix_data:
            mnc, operator_name = prefix_data
        else:
            mnc, operator_name = None, None
        
        # Get city hint
        city_hint = PAKISTAN_CITY_PREFIX_MAP.get(prefix)
        
        if operator_name and mnc:
            carrier_info = f"{operator_name} Pakistan (MCC={mcc}, MNC={mnc})"
        else:
            carrier_info = f"Pakistan (MCC={mcc}, prefix={prefix})"
        
        return "92", prefix, mcc, mnc, carrier_info, city_hint
    
    return None, None, None, None, None, None

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
