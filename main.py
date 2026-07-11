from flask import Flask, request, jsonify, render_template_string
from datetime import datetime

app = Flask(__name__)
devices = []

HTML = """
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
    </style>
</head>
<body>
    <h1>Device MAC Address Monitor</h1>
    <p class="count">Total Devices: <b>{{ count }}</b></p>
    <p style="color:#888;">Auto-refreshes every 10 seconds</p>
    <table>
        <tr>
            <th>#</th><th>Device Name</th><th>WiFi MAC Address</th><th>IP Address</th><th>Time</th>
        </tr>
        {% for d in devices %}
        <tr>
            <td>{{ loop.index }}</td>
            <td>{{ d.hostname }}</td>
            <td><b>{{ d.mac }}</b></td>
            <td>{{ d.ip }}</td>
            <td>{{ d.timestamp }}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

@app.route('/register-device', methods=['POST'])
def register_device():
    data = request.json
    devices.append({
        "mac": data.get('mac_address'),
        "hostname": data.get('hostname'),
        "ip": request.remote_addr,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    return jsonify({"status": "success"}), 200

@app.route('/')
def dashboard():
    return render_template_string(HTML, devices=devices, count=len(devices))

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)