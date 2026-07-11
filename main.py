from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import qrcode
import io
import base64

app = Flask(__name__)
devices = []

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Device MAC Monitor</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
        h1 { color: #00d4ff; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th { background: #00d4ff; color: #000; padding: 10px; text-align: left; }
        td { padding: 10px; border-bottom: 1px solid #333; }
        tr:hover { background: #16213e; }
        .count { color: #00d4ff; font-size: 18px; }
        .qr-section { margin-top: 30px; padding: 20px; background: #16213e; border-radius: 10px; text-align: center; }
        .qr-section img { margin-top: 10px; border: 4px solid #00d4ff; border-radius: 8px; }
        .qr-section p { color: #aaa; font-size: 14px; }
        .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
        .windows { background: #0078d4; color: #fff; }
        .android { background: #3ddc84; color: #000; }
        .other { background: #888; color: #fff; }
    </style>
</head>
<body>
    <h1>Device MAC Address Monitor</h1>
    <p class="count">Total Devices: <b>{{ count }}</b></p>
    <p style="color:#888;">Auto-refreshes every 10 seconds</p>

    <table>
        <tr>
            <th>#</th>
            <th>Device Name</th>
            <th>WiFi MAC / Device Info</th>
            <th>IP Address</th>
            <th>Type</th>
            <th>Time</th>
        </tr>
        {% for d in devices %}
        <tr>
            <td>{{ loop.index }}</td>
            <td>{{ d.hostname }}</td>
            <td><b>{{ d.mac }}</b></td>
            <td>{{ d.ip }}</td>
            <td><span class="badge {{ d.type|lower }}">{{ d.type }}</span></td>
            <td>{{ d.timestamp }}</td>
        </tr>
        {% endfor %}
    </table>

    <div class="qr-section">
        <h2 style="color:#00d4ff;">Scan with Android / iPhone</h2>
        <p>Share this QR code — anyone who scans it will be registered automatically</p>
        <img src="/qr" width="200" height="200" alt="QR Code"/>
        <p style="margin-top:10px;">Or share this link:<br>
        <a href="/scan" style="color:#00d4ff;">{{ scan_url }}</a></p>
    </div>
</body>
</html>
"""

SCAN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Device Registration</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; 
               display: flex; flex-direction: column; align-items: center; 
               justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }
        h1 { color: #00d4ff; text-align: center; }
        .card { background: #16213e; border-radius: 15px; padding: 30px; 
                max-width: 400px; width: 100%; text-align: center; }
        .status { font-size: 18px; margin: 20px 0; }
        .success { color: #3ddc84; }
        .info { color: #aaa; font-size: 14px; margin-top: 10px; }
        .mac { font-size: 22px; font-weight: bold; color: #00d4ff; 
               background: #0d1117; padding: 10px 20px; border-radius: 8px; 
               margin: 15px 0; letter-spacing: 2px; }
    </style>
    <script>
        window.onload = function() {
            var info = {
                hostname: navigator.userAgent.substring(0, 50),
                mac_address: "Android/Browser - IP Only",
                type: "Android"
            };
            fetch('/register-device', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(info)
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('status').innerHTML = 
                    '<span class="success">✓ Registered Successfully!</span>';
                document.getElementById('info').innerHTML = 
                    'Your device has been registered on the dashboard.';
            })
            .catch(e => {
                document.getElementById('status').innerHTML = 'Registration failed. Try again.';
            });
        }
    </script>
</head>
<body>
    <div class="card">
        <h1>Device Registration</h1>
        <div class="mac">📱 Mobile Device</div>
        <div class="status" id="status">Registering your device...</div>
        <div class="info" id="info">Please wait...</div>
        <p class="info">Your device info will appear on the monitoring dashboard.</p>
    </div>
</body>
</html>
"""

@app.route('/register-device', methods=['POST'])
def register_device():
    data = request.json
    device_type = data.get('type', 'Windows')
    devices.append({
        "mac": data.get('mac_address'),
        "hostname": data.get('hostname'),
        "ip": request.remote_addr,
        "type": device_type,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    return jsonify({"status": "success"}), 200

@app.route('/')
def dashboard():
    scan_url = request.host_url + "scan"
    return render_template_string(DASHBOARD_HTML, devices=devices, count=len(devices), scan_url=scan_url)

@app.route('/scan')
def scan():
    return render_template_string(SCAN_HTML)

@app.route('/qr')
def qr_code():
    scan_url = request.host_url + "scan"
    img = qrcode.make(scan_url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.getvalue(), 200, {'Content-Type': 'image/png'}

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
