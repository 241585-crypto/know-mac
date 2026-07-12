from flask import Flask, request, jsonify, render_template_string, Response
from datetime import datetime
import json

app = Flask(__name__)
devices = []

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Device Registration Dashboard</title>
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
        td { padding: 10px; border-bottom: 1px solid #222; font-size: 12px; word-break: break-all; }
        tr:hover { background: #16213e; }
        .duplicate { background: #ff000022; }
        .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; }
        .windows { background: #0078d4; color: #fff; }
        .fingerprint { color: #00d4ff; font-family: monospace; font-size: 11px; }
        .detail-btn { background: #00d4ff; color: #000; border: none; padding: 4px 10px;
                      border-radius: 5px; cursor: pointer; font-size: 11px; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                 background: rgba(0,0,0,0.8); z-index: 1000; justify-content: center; align-items: center; }
        .modal.active { display: flex; }
        .modal-content { background: #16213e; border-radius: 15px; padding: 25px;
                         max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; }
        .modal-content h2 { color: #00d4ff; margin-bottom: 15px; }
        .modal-content table { font-size: 12px; }
        .modal-content td { padding: 6px 10px; }
        .modal-content td:first-child { color: #888; width: 40%; }
        .modal-content td:last-child { color: #00d4ff; font-family: monospace; }
        .close-btn { background: #ff6b6b; color: #fff; border: none; padding: 8px 20px;
                     border-radius: 5px; cursor: pointer; margin-top: 15px; }
    </style>
</head>
<body>
    <h1>📡 Device Registration Dashboard</h1>
    <p class="subtitle">Auto-refreshes every 10 seconds</p>

    <div class="stats">
        <div class="stat-card">
            <div class="number">{{ count }}</div>
            <div class="label">Total Registrations</div>
        </div>
        <div class="stat-card">
            <div class="number">{{ unique_count }}</div>
            <div class="label">Unique Devices</div>
        </div>
        <div class="stat-card">
            <div class="number">{{ duplicate_count }}</div>
            <div class="label">Duplicates</div>
        </div>
    </div>

    <table>
        <tr>
            <th>#</th>
            <th>Hostname</th>
            <th>WiFi MAC</th>
            <th>CPU ID</th>
            <th>Board Serial</th>
            <th>BIOS Serial</th>
            <th>Disk Serial</th>
            <th>System UUID</th>
            <th>Fingerprint</th>
            <th>IP</th>
            <th>Duplicate</th>
            <th>Time</th>
            <th>Details</th>
        </tr>
        {% for d in devices %}
        <tr class="{{ 'duplicate' if d.is_duplicate else '' }}">
            <td>{{ loop.index }}</td>
            <td>{{ d.hostname }}</td>
            <td>{{ d.mac }}</td>
            <td>{{ d.hardware.cpu_id if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.board_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.bios_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.disk_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.system_uuid if d.hardware else 'N/A' }}</td>
            <td><span class="fingerprint">{{ d.fingerprint[:16] }}...</span></td>
            <td>{{ d.ip }}</td>
            <td>{{ '⚠️ YES' if d.is_duplicate else '✅ No' }}</td>
            <td>{{ d.timestamp }}</td>
            <td>
                <button class="detail-btn" onclick="showDetail({{ loop.index0 }})">View</button>
            </td>
        </tr>
        {% endfor %}
    </table>

    <!-- Detail Modal -->
    <div class="modal" id="modal">
        <div class="modal-content">
            <h2>📋 Device Details</h2>
            <div id="modal-body"></div>
            <button class="close-btn" onclick="closeModal()">Close</button>
        </div>
    </div>

    <script>
        var devices = {{ devices_json }};

        function showDetail(index) {
            var d = devices[index];
            var hw = d.hardware || {};
            var html = '<table>';
            html += '<tr><td>Hostname</td><td>' + (d.hostname || 'N/A') + '</td></tr>';
            html += '<tr><td>WiFi MAC</td><td>' + (d.mac || 'N/A') + '</td></tr>';
            html += '<tr><td>Fingerprint</td><td>' + (d.fingerprint || 'N/A') + '</td></tr>';
            html += '<tr><td>IP Address</td><td>' + (d.ip || 'N/A') + '</td></tr>';
            html += '<tr><td>OS</td><td>' + (hw.os || 'N/A') + '</td></tr>';
            html += '<tr><td>CPU Name</td><td>' + (hw.cpu_name || 'N/A') + '</td></tr>';
            html += '<tr><td>CPU ID</td><td>' + (hw.cpu_id || 'N/A') + '</td></tr>';
            html += '<tr><td>Board Serial</td><td>' + (hw.board_serial || 'N/A') + '</td></tr>';
            html += '<tr><td>BIOS Serial</td><td>' + (hw.bios_serial || 'N/A') + '</td></tr>';
            html += '<tr><td>Disk Serial</td><td>' + (hw.disk_serial || 'N/A') + '</td></tr>';
            html += '<tr><td>RAM Serial</td><td>' + (hw.ram_serial || 'N/A') + '</td></tr>';
            html += '<tr><td>GPU Name</td><td>' + (hw.gpu_name || 'N/A') + '</td></tr>';
            html += '<tr><td>System UUID</td><td>' + (hw.system_uuid || 'N/A') + '</td></tr>';
            html += '<tr><td>Duplicate</td><td>' + (d.is_duplicate ? '⚠️ YES' : '✅ No') + '</td></tr>';
            html += '<tr><td>Time</td><td>' + (d.timestamp || 'N/A') + '</td></tr>';

            if (hw.all_macs && hw.all_macs.length > 0) {
                html += '<tr><td>All MACs</td><td>';
                hw.all_macs.forEach(function(m) {
                    html += m.adapter + ': ' + m.mac + '<br>';
                });
                html += '</td></tr>';
            }
            html += '</table>';
            document.getElementById('modal-body').innerHTML = html;
            document.getElementById('modal').classList.add('active');
        }

        function closeModal() {
            document.getElementById('modal').classList.remove('active');
        }
    </script>
</body>
</html>
"""

@app.route('/register-device', methods=['POST'])
def register_device():
    data = request.json
    mac = data.get('mac_address', 'N/A')
    fingerprint = data.get('fingerprint', 'N/A')
    hostname = data.get('hostname', 'Unknown')
    device_type = data.get('type', 'Other')
    hardware = data.get('hardware', {})

    is_duplicate = any(
        d['fingerprint'] == fingerprint and fingerprint != 'N/A'
        for d in devices
    )

    devices.append({
        "mac": mac,
        "fingerprint": fingerprint,
        "hostname": hostname,
        "ip": request.remote_addr,
        "type": device_type,
        "hardware": hardware,
        "is_duplicate": is_duplicate,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

    return jsonify({
        "status": "success",
        "is_duplicate": is_duplicate
    }), 200

@app.route('/')
def dashboard():
    duplicate_count = sum(1 for d in devices if d['is_duplicate'])
    fingerprints = set(d['fingerprint'] for d in devices if d['fingerprint'] != 'N/A')
    unique_count = len(fingerprints)

    return render_template_string(DASHBOARD_HTML,
        devices=devices,
        count=len(devices),
        unique_count=unique_count,
        duplicate_count=duplicate_count,
        devices_json=json.dumps(devices))

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
