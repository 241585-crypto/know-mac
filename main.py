from flask import Flask, request, jsonify, render_template_string, Response
from datetime import datetime
import re
import json

app = Flask(__name__)
devices = []

def parse_user_agent(ua):
    try:
        info = json.loads(ua)
        ua_str = info.get('ua', '')
        screen = info.get('screen', '')
        memory = info.get('memory', '')
        cores = info.get('cores', '')
    except:
        ua_str = ua
        screen = ''
        memory = ''
        cores = ''

    ua_lower = ua_str.lower()

    if 'iphone' in ua_lower:
        match = re.search(r'os (\d+)_', ua_lower)
        version = match.group(1) if match else ''
        return f"iPhone (iOS {version}) {screen}".strip(), "iOS"

    elif 'ipad' in ua_lower:
        match = re.search(r'os (\d+)_', ua_lower)
        version = match.group(1) if match else ''
        return f"iPad (iOS {version}) {screen}".strip(), "iOS"

    elif 'android' in ua_lower:
        version_match = re.search(r'android (\d+)', ua_lower)
        version = version_match.group(1) if version_match else ''
        brand = 'Android'
        for b in ['samsung', 'xiaomi', 'redmi', 'huawei', 'oppo', 'vivo',
                  'realme', 'oneplus', 'nokia', 'motorola', 'lg', 'sony']:
            if b in ua_lower:
                brand = b.capitalize()
                break
        extras = []
        if screen: extras.append(screen)
        if memory and memory != 'Unknown': extras.append(f"{memory}GB RAM")
        if cores and cores != 'Unknown': extras.append(f"{cores} cores")
        extra_str = ' | '.join(extras)
        return f"{brand} (Android {version}) {extra_str}".strip(), "Android"

    elif 'windows' in ua_lower:
        return "Windows PC", "Windows"

    elif 'macintosh' in ua_lower:
        return "Mac", "Mac"

    return "Unknown Device", "Other"

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MAC Registration</title>
    <meta http-equiv="refresh" content="10">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
        h1 { color: #00d4ff; margin-bottom: 5px; }
        .subtitle { color: #888; font-size: 14px; margin-bottom: 20px; }
        .stats { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
        .stat-card { background: #16213e; border-radius: 10px; padding: 15px 25px; text-align: center; min-width: 120px; }
        .stat-card .number { font-size: 28px; font-weight: bold; color: #00d4ff; }
        .stat-card .label { font-size: 12px; color: #888; margin-top: 4px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th { background: #00d4ff; color: #000; padding: 12px 10px; text-align: left; font-size: 13px; }
        td { padding: 10px; border-bottom: 1px solid #222; font-size: 13px; }
        tr:hover { background: #16213e; }
        .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; }
        .windows { background: #0078d4; color: #fff; }
        .android { background: #3ddc84; color: #000; }
        .ios { background: #555; color: #fff; }
        .mac { background: #aaa; color: #000; }
        .network { background: #ff9800; color: #000; }
        .other { background: #444; color: #fff; }
        .qr-section { margin-top: 35px; padding: 25px; background: #16213e; border-radius: 12px; text-align: center; }
        .qr-section h2 { color: #00d4ff; margin-bottom: 8px; }
        .qr-section p { color: #aaa; font-size: 14px; margin-bottom: 15px; }
        .qr-section img { border: 4px solid #00d4ff; border-radius: 10px; }
        .scan-link { color: #00d4ff; word-break: break-all; font-size: 14px; margin-top: 10px; display: block; }
        .na { color: #666; font-style: italic; }
    </style>
</head>
<body>
    <h1>📡 MAC Registration</h1>
    <p class="subtitle">Auto-refreshes every 10 seconds</p>

    <div class="stats">
        <div class="stat-card">
            <div class="number">{{ count }}</div>
            <div class="label">Total Devices</div>
        </div>
        <div class="stat-card">
            <div class="number">{{ windows_count }}</div>
            <div class="label">Windows</div>
        </div>
        <div class="stat-card">
            <div class="number">{{ android_count }}</div>
            <div class="label">Android</div>
        </div>
        <div class="stat-card">
            <div class="number">{{ ios_count }}</div>
            <div class="label">iOS</div>
        </div>
        <div class="stat-card">
            <div class="number">{{ network_count }}</div>
            <div class="label">Network Scan</div>
        </div>
    </div>

    <table>
        <tr>
            <th>#</th>
            <th>Device Name</th>
            <th>WiFi MAC Address</th>
            <th>IP Address</th>
            <th>Type</th>
            <th>Time</th>
        </tr>
        {% for d in devices %}
        <tr>
            <td>{{ loop.index }}</td>
            <td>{{ d.hostname }}</td>
            <td>
                {% if d.mac == 'N/A' or 'Mobile' in d.mac %}
                    <span class="na">Not available on {{ d.type }}</span>
                {% else %}
                    <b>{{ d.mac }}</b>
                {% endif %}
            </td>
            <td>{{ d.ip }}</td>
            <td><span class="badge {{ d.type|lower }}">{{ d.type }}</span></td>
            <td>{{ d.timestamp }}</td>
        </tr>
        {% endfor %}
    </table>

    <div class="qr-section">
        <h2>📱 Scan to Register Mobile Device</h2>
        <p>Android & iPhone users scan this QR code to register automatically</p>
        <img src="https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={{ scan_url }}"
             width="220" height="220" alt="QR Code"/>
        <a class="scan-link" href="/scan">{{ scan_url }}</a>
    </div>
</body>
</html>
"""

SCAN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>MAC Registration</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="manifest" href="/manifest.json">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-title" content="MAC Registration">
    <meta name="theme-color" content="#1a1a2e">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee;
               display: flex; align-items: center; justify-content: center;
               min-height: 100vh; padding: 20px; }
        .card { background: #16213e; border-radius: 20px; padding: 35px 30px;
                max-width: 380px; width: 100%; text-align: center; }
        h1 { color: #00d4ff; font-size: 22px; margin-bottom: 8px; }
        .icon { font-size: 60px; margin: 15px 0; }
        .status { font-size: 16px; margin: 20px 0 10px; min-height: 24px; }
        .success { color: #3ddc84; }
        .error { color: #ff6b6b; }
        .info { color: #aaa; font-size: 13px; line-height: 1.6; }
        .detail { background: #0d1117; border-radius: 10px; padding: 12px 15px;
                  margin: 15px 0; font-size: 13px; text-align: left; }
        .detail p { margin: 4px 0; color: #aaa; }
        .detail span { color: #00d4ff; }
        .install-hint { margin-top: 20px; padding: 12px; background: #0d1117;
                        border-radius: 10px; font-size: 12px; color: #666; }
    </style>
    <script>
        window.onload = function() {
            var ua = navigator.userAgent;
            var deviceType = 'Mobile';
            if (/android/i.test(ua)) deviceType = 'Android';
            else if (/iphone|ipad/i.test(ua)) deviceType = 'iOS';

            var deviceInfo = {
                ua: ua,
                platform: navigator.platform || 'Unknown',
                language: navigator.language || 'Unknown',
                screen: screen.width + 'x' + screen.height,
                cores: navigator.hardwareConcurrency || 'Unknown',
                memory: navigator.deviceMemory || 'Unknown'
            };

            document.getElementById('device-type').textContent = deviceType;
            document.getElementById('device-ua').textContent = ua.substring(0, 80) + '...';
            document.getElementById('device-screen').textContent = deviceInfo.screen;
            document.getElementById('device-memory').textContent =
                deviceInfo.memory !== 'Unknown' ? deviceInfo.memory + ' GB' : 'Unknown';
            document.getElementById('device-cores').textContent = deviceInfo.cores;

            fetch('/register-device', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    hostname: JSON.stringify(deviceInfo),
                    mac_address: 'N/A',
                    type: deviceType
                })
            })
            .then(r => r.json())
            .then(function() {
                document.getElementById('status').innerHTML =
                    '<span class="success">✓ Registered Successfully!</span>';
                document.getElementById('info').textContent =
                    'Your device is now showing on the dashboard.';
            })
            .catch(function() {
                document.getElementById('status').innerHTML =
                    '<span class="error">✗ Failed. Check your connection.</span>';
            });
        }
    </script>
</head>
<body>
    <div class="card">
        <h1>📡 MAC Registration</h1>
        <div class="icon">📱</div>
        <div class="status" id="status">Registering your device...</div>
        <div class="detail">
            <p>Type: <span id="device-type">Detecting...</span></p>
            <p>Screen: <span id="device-screen">Detecting...</span></p>
            <p>RAM: <span id="device-memory">Detecting...</span></p>
            <p>CPU Cores: <span id="device-cores">Detecting...</span></p>
            <p>Agent: <span id="device-ua">Detecting...</span></p>
        </div>
        <p class="info" id="info">Please wait while we register your device...</p>
        <div class="install-hint">
            💡 iPhone users: tap Share → "Add to Home Screen" to install this app
        </div>
    </div>
</body>
</html>
"""

MANIFEST = {
    "name": "MAC Registration",
    "short_name": "MAC Reg",
    "start_url": "/scan",
    "display": "standalone",
    "background_color": "#1a1a2e",
    "theme_color": "#00d4ff",
    "icons": [
        {
            "src": "https://api.qrserver.com/v1/create-qr-code/?size=192x192&data=MAC",
            "sizes": "192x192",
            "type": "image/png"
        }
    ]
}

@app.route('/register-device', methods=['POST'])
def register_device():
    data = request.json
    ua = data.get('hostname', '')
    mac = data.get('mac_address', 'N/A')
    device_type = data.get('type', 'Other')

    if device_type in ['Android', 'iOS', 'Mobile']:
        hostname, device_type = parse_user_agent(ua)
    else:
        hostname = data.get('hostname', 'Unknown')

    devices.append({
        "mac": mac,
        "hostname": hostname,
        "ip": request.remote_addr,
        "type": device_type,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    return jsonify({"status": "success"}), 200

@app.route('/')
def dashboard():
    scan_url = request.host_url.rstrip('/') + "/scan"
    windows_count = sum(1 for d in devices if d['type'] == 'Windows')
    android_count = sum(1 for d in devices if d['type'] == 'Android')
    ios_count = sum(1 for d in devices if d['type'] == 'iOS')
    network_count = sum(1 for d in devices if d['type'] == 'Network')
    return render_template_string(DASHBOARD_HTML,
        devices=devices,
        count=len(devices),
        windows_count=windows_count,
        android_count=android_count,
        ios_count=ios_count,
        network_count=network_count,
        scan_url=scan_url)

@app.route('/scan')
def scan():
    return render_template_string(SCAN_HTML)

@app.route('/manifest.json')
def manifest():
    return Response(json.dumps(MANIFEST), mimetype='application/json')

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
