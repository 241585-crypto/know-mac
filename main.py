from flask import Flask, request, jsonify, render_template_string, Response
from datetime import datetime
import json
import os

app = Flask(__name__)
devices = []

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return response

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Device Registration Dashbord</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
        h1 { color: #00d4ff; margin-bottom: 20px; }
        .stats { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
        .stat-card { background: #16213e; border-radius: 10px; padding: 15px 25px; text-align: center; min-width: 120px; }
        .stat-card .number { font-size: 28px; font-weight: bold; color: #00d4ff; }
        .stat-card .label { font-size: 12px; color: #888; margin-top: 4px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th { background: #00d4ff; color: #000; padding: 12px 10px; text-align: left; font-size: 12px; white-space: nowrap; }
        td { padding: 10px; border-bottom: 1px solid #222; font-size: 12px; word-break: break-all; }
        tr:hover { background: #16213e; }
        .duplicate { background: #ff000022; }
        .fingerprint { color: #00d4ff; font-family: monospace; font-size: 11px; }
        .detail-btn { background: #00d4ff; color: #000; border: none; padding: 4px 10px;
                      border-radius: 5px; cursor: pointer; font-size: 11px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
                 font-size: 10px; font-weight: bold; white-space: nowrap; }
        .badge-wifi      { background: #00d4ff22; color: #00d4ff; border: 1px solid #00d4ff55; }
        .badge-ethernet  { background: #00ff8822; color: #00ff88; border: 1px solid #00ff8855; }
        .badge-vpn       { background: #ff990022; color: #ff9900; border: 1px solid #ff990055; }
        .badge-virtual   { background: #aa44ff22; color: #bb66ff; border: 1px solid #aa44ff55; }
        .badge-bluetooth { background: #0066ff22; color: #4499ff; border: 1px solid #0066ff55; }
        .badge-other     { background: #88888822; color: #aaa;    border: 1px solid #88888855; }
        .status-connected    { color: #00ff88; font-weight: bold; }
        .status-disconnected { color: #ff6b6b; }
        .status-unknown      { color: #888; }

        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                 background: rgba(0,0,0,0.8); z-index: 1000; justify-content: center; align-items: center; }
        .modal.active { display: flex; }
        .modal-content { background: #16213e; border-radius: 15px; padding: 25px;
                         max-width: 750px; width: 90%; max-height: 85vh; overflow-y: auto; }
        .modal-content h2 { color: #00d4ff; margin-bottom: 15px; }
        .modal-table { width: 100%; border-collapse: collapse; }
        .modal-table td { padding: 8px 10px; border-bottom: 1px solid #222; font-size: 13px; }
        .modal-table td:first-child { color: #888; width: 35%; white-space: nowrap; }
        .modal-table td:last-child { color: #eee; font-family: monospace; word-break: break-all; }
        .section-header { background: #00d4ff22; color: #00d4ff; padding: 8px 10px;
                          font-weight: bold; font-size: 13px; }
        .adapter-block { background: #0d1117; margin: 5px 0; border-radius: 6px; padding: 8px 12px; }
        .adapter-name { color: #00d4ff; font-weight: bold; margin-bottom: 6px; font-size: 12px;
                        display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .adapter-detail { color: #aaa; font-size: 11px; margin: 2px 0; font-family: monospace; }
        .adapter-detail span { color: #eee; }
        .close-btn { background: #ff6b6b; color: #fff; border: none; padding: 8px 20px;
                     border-radius: 5px; cursor: pointer; margin-top: 15px; width: 100%; font-size: 14px; }
    </style>
</head>
<body>
    <h1>&#128225; Device Registration Dashboard</h1>

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
        <div class="stat-card">
            <div class="number">{{ hta_count }}</div>
            <div class="label">Via .HTA</div>
        </div>
        <div class="stat-card">
            <div class="number">{{ browser_count }}</div>
            <div class="label">Via Browser</div>
        </div>
    </div>

    <table>
        <tr>
            <th>#</th>
            <th>Hostname</th>
            <th>WiFi MAC</th>
            <th>LAN MAC</th>
            <th>BT MAC</th>
            <th>CPU ID</th>
            <th>Board Serial</th>
            <th>BIOS Serial</th>
            <th>Disk Serial</th>
            <th>System UUID</th>
            <th>Fingerprint</th>
            <th>Local IP</th>
            <th>Public IP</th>
            <th>Duplicate</th>
            <th>Time</th>
            <th>Details</th>
        </tr>
        {% for d in devices %}
        <tr class="{{ 'duplicate' if d.is_duplicate else '' }}">
            <td>{{ loop.index }}</td>
            <td>{{ d.hostname }}</td>
            <td>{{ d.hardware.wifi_mac if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.lan_mac if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.bluetooth_mac if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.cpu_id if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.board_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.bios_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.disk_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.system_uuid if d.hardware else 'N/A' }}</td>
            <td><span class="fingerprint">{{ d.fingerprint[:16] }}...</span></td>
            <td>{{ d.hardware.local_ip if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.public_ip if d.hardware else 'N/A' }}</td>
            <td>{{ '&#9888;&#65039; YES' if d.is_duplicate else '&#9989; No' }}</td>
            <td>{{ d.timestamp }}</td>
            <td><button class="detail-btn" onclick="showDetail({{ loop.index0 }})">View</button></td>
        </tr>
        {% endfor %}
    </table>

    <div class="modal" id="modal">
        <div class="modal-content">
            <h2>&#128203; Full Device Details</h2>
            <div id="modal-body"></div>
            <button class="close-btn" onclick="closeModal()">&#10005; Close</button>
        </div>
    </div>

    <script>
        var devices = {{ devices_json | safe }};

        function val(v) { return (v !== null && v !== undefined && v !== '') ? String(v) : 'N/A'; }

        function typeBadge(type) {
            var map = {
                'WiFi':      'badge-wifi',
                'Ethernet':  'badge-ethernet',
                'VPN':       'badge-vpn',
                'Virtual':   'badge-virtual',
                'Bluetooth': 'badge-bluetooth'
            };
            var cls = map[type] || 'badge-other';
            return '<span class="badge ' + cls + '">' + val(type) + '</span>';
        }

        function statusBadge(status) {
            var cls = 'status-unknown';
            if (status === 'Connected') cls = 'status-connected';
            if (status === 'Disconnected' || status === 'Media Disconnected') cls = 'status-disconnected';
            return '<span class="' + cls + '">' + val(status) + '</span>';
        }

        function showDetail(index) {
            var d  = devices[index];
            var hw = d.hardware || {};
            var html = '<table class="modal-table">';

            // System
            html += '<tr><td colspan="2" class="section-header">&#128421; SYSTEM</td></tr>';
            html += '<tr><td>Hostname</td><td>'      + val(d.hostname)             + '</td></tr>';
            html += '<tr><td>OS</td><td>'            + val(hw.os)                  + '</td></tr>';
            html += '<tr><td>Manufacturer</td><td>'  + val(hw.system_manufacturer) + '</td></tr>';
            html += '<tr><td>Model</td><td>'         + val(hw.system_model)        + '</td></tr>';
            html += '<tr><td>System Serial</td><td>' + val(hw.system_serial)       + '</td></tr>';
            html += '<tr><td>System UUID</td><td>'   + val(hw.system_uuid)         + '</td></tr>';

            // Network Summary
            html += '<tr><td colspan="2" class="section-header">&#127760; NETWORK SUMMARY</td></tr>';
            html += '<tr><td>WiFi MAC</td><td>'      + val(hw.wifi_mac)      + '</td></tr>';
            html += '<tr><td>LAN MAC</td><td>'       + val(hw.lan_mac)       + '</td></tr>';
            html += '<tr><td>Bluetooth MAC</td><td>' + val(hw.bluetooth_mac) + '</td></tr>';
            html += '<tr><td>Local IP</td><td>'      + val(hw.local_ip)      + '</td></tr>';
            html += '<tr><td>Public IP</td><td>'     + val(hw.public_ip)     + '</td></tr>';
            html += '</table>';

            // All Adapters
            html += '<div style="margin-top:10px">';
            html += '<div class="section-header" style="margin-bottom:8px">&#128225; ALL NETWORK ADAPTERS</div>';
            if (hw.all_adapters && hw.all_adapters.length > 0) {
                hw.all_adapters.forEach(function(a) {
                    html += '<div class="adapter-block">';
                    html += '<div class="adapter-name">' + val(a.name) + ' '
                          + typeBadge(a.adapter_type) + ' '
                          + statusBadge(a.connection_status) + '</div>';
                    html += '<div class="adapter-detail">MAC:         <span>' + val(a.mac)             + '</span></div>';
                    html += '<div class="adapter-detail">IP:          <span>' + val(a.ip)              + '</span></div>';
                    html += '<div class="adapter-detail">Subnet:      <span>' + val(a.subnet)          + '</span></div>';
                    html += '<div class="adapter-detail">Gateway:     <span>' + val(a.gateway)         + '</span></div>';
                    html += '<div class="adapter-detail">DHCP:        <span>' + val(a.dhcp)            + '</span></div>';
                    html += '<div class="adapter-detail">DHCP Server: <span>' + val(a.dhcp_server)     + '</span></div>';
                    html += '<div class="adapter-detail">DNS:         <span>' + val(a.dns_servers)     + '</span></div>';
                    html += '</div>';
                });
            } else {
                html += '<div style="color:#888;padding:10px">No adapter data (Browser registration)</div>';
            }
            html += '</div>';

            // Bluetooth Adapters (from EXE/HTA only)
            if (hw.bluetooth_adapters && hw.bluetooth_adapters.length > 0) {
                html += '<div style="margin-top:10px">';
                html += '<div class="section-header" style="margin-bottom:8px">&#128246; BLUETOOTH ADAPTERS</div>';
                hw.bluetooth_adapters.forEach(function(b) {
                    html += '<div class="adapter-block">';
                    html += '<div class="adapter-name">&#128309; ' + val(b.name) + '</div>';
                    html += '<div class="adapter-detail">MAC:          <span>' + val(b.mac)          + '</span></div>';
                    html += '<div class="adapter-detail">Manufacturer: <span>' + val(b.manufacturer) + '</span></div>';
                    html += '<div class="adapter-detail">Device ID:    <span>' + val(b.device_id)    + '</span></div>';
                    html += '</div>';
                });
                html += '</div>';
            }

            html += '<table class="modal-table" style="margin-top:10px">';

            // CPU
            html += '<tr><td colspan="2" class="section-header">&#9881; CPU</td></tr>';
            html += '<tr><td>Name</td><td>'          + val(hw.cpu_name)    + '</td></tr>';
            html += '<tr><td>ID</td><td>'            + val(hw.cpu_id)      + '</td></tr>';
            html += '<tr><td>Cores/Threads</td><td>' + val(hw.cpu_cores)   + ' / ' + val(hw.cpu_threads) + '</td></tr>';
            html += '<tr><td>Speed</td><td>'         + val(hw.cpu_speed)   + ' MHz</td></tr>';

            // Motherboard
            html += '<tr><td colspan="2" class="section-header">&#9638; MOTHERBOARD</td></tr>';
            html += '<tr><td>Manufacturer</td><td>'  + val(hw.board_manufacturer) + '</td></tr>';
            html += '<tr><td>Product</td><td>'       + val(hw.board_product)      + '</td></tr>';
            html += '<tr><td>Version</td><td>'       + val(hw.board_version)      + '</td></tr>';
            html += '<tr><td>Serial</td><td>'        + val(hw.board_serial)       + '</td></tr>';

            // BIOS
            html += '<tr><td colspan="2" class="section-header">&#128190; BIOS</td></tr>';
            html += '<tr><td>Manufacturer</td><td>'  + val(hw.bios_manufacturer) + '</td></tr>';
            html += '<tr><td>Version</td><td>'       + val(hw.bios_version)      + '</td></tr>';
            html += '<tr><td>Serial</td><td>'        + val(hw.bios_serial)       + '</td></tr>';
            html += '<tr><td>Date</td><td>'          + val(hw.bios_date)         + '</td></tr>';

            // Disk
            html += '<tr><td colspan="2" class="section-header">&#128191; DISK</td></tr>';
            html += '<tr><td>Model</td><td>'         + val(hw.disk_model)  + '</td></tr>';
            html += '<tr><td>Serial</td><td>'        + val(hw.disk_serial) + '</td></tr>';
            html += '<tr><td>Size</td><td>'          + val(hw.disk_size)   + ' GB</td></tr>';

            // RAM
            html += '<tr><td colspan="2" class="section-header">&#129504; RAM</td></tr>';
            html += '<tr><td>Manufacturer</td><td>'  + val(hw.ram_manufacturer) + '</td></tr>';
            html += '<tr><td>Serial</td><td>'        + val(hw.ram_serial)       + '</td></tr>';
            html += '<tr><td>Speed</td><td>'         + val(hw.ram_speed)        + ' MHz</td></tr>';
            html += '<tr><td>Capacity</td><td>'      + val(hw.ram_capacity)     + ' GB</td></tr>';

            // GPU
            html += '<tr><td colspan="2" class="section-header">&#127918; GPU</td></tr>';
            html += '<tr><td>Name</td><td>'          + val(hw.gpu_name)   + '</td></tr>';
            html += '<tr><td>Driver</td><td>'        + val(hw.gpu_driver) + '</td></tr>';
            html += '<tr><td>VRAM</td><td>'          + val(hw.gpu_ram)    + ' GB</td></tr>';

            // Browser signals (shown only for browser registrations)
            if (hw.canvas_fp || hw.webgl_renderer || hw.audio_fp) {
                html += '<tr><td colspan="2" class="section-header">&#127760; BROWSER SIGNALS</td></tr>';
                html += '<tr><td>WebGL Renderer</td><td>' + val(hw.webgl_renderer)  + '</td></tr>';
                html += '<tr><td>Screen</td><td>'         + val(hw.screen)          + '</td></tr>';
                html += '<tr><td>Cores</td><td>'          + val(hw.cores)           + '</td></tr>';
                html += '<tr><td>Memory</td><td>'         + val(hw.memory)          + ' GB</td></tr>';
                html += '<tr><td>Timezone</td><td>'       + val(hw.timezone)        + '</td></tr>';
                html += '<tr><td>Languages</td><td>'      + val(hw.languages)       + '</td></tr>';
                html += '<tr><td>Fonts Detected</td><td>' + val(hw.fonts_detected)  + '</td></tr>';
                html += '<tr><td>Media Devices</td><td>'  + val(hw.media_devices)   + '</td></tr>';
                html += '<tr><td>Audio FP</td><td>'       + val(hw.audio_fp)        + '</td></tr>';
                html += '<tr><td>Canvas FP</td><td>'      + val(hw.canvas_fp)       + '</td></tr>';
                html += '<tr><td>Referrer</td><td>'       + val(hw.referrer)        + '</td></tr>';
            }

            // Security
            html += '<tr><td colspan="2" class="section-header">&#128272; SECURITY</td></tr>';
            html += '<tr><td>Fingerprint</td><td>'   + val(d.fingerprint) + '</td></tr>';
            html += '<tr><td>Duplicate</td><td>'     + (d.is_duplicate ? '&#9888;&#65039; YES - Same device registered before' : '&#9989; No') + '</td></tr>';
            html += '<tr><td>Registered At</td><td>' + val(d.timestamp)   + '</td></tr>';

            html += '</table>';

            document.getElementById('modal-body').innerHTML = html;
            document.getElementById('modal').classList.add('active');
        }

        function closeModal() {
            document.getElementById('modal').classList.remove('active');
        }

        document.getElementById('modal').addEventListener('click', function(e) {
            if (e.target === this) closeModal();
        });
    </script>
</body>
</html>
"""

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/register-device', methods=['POST', 'OPTIONS'])
def register_device():
    if request.method == 'OPTIONS':
        return '', 200

    data        = request.json or {}
    mac         = data.get('mac_address', 'N/A')
    fingerprint = data.get('fingerprint', 'N/A')
    hostname    = data.get('hostname', 'Unknown')
    device_type = data.get('type', 'Other')
    hardware    = data.get('hardware', {})

    is_duplicate = any(
        d['fingerprint'] == fingerprint and fingerprint != 'N/A'
        for d in devices
    )

    devices.append({
        "mac":          mac,
        "fingerprint":  fingerprint,
        "hostname":     hostname,
        "ip":           request.remote_addr,
        "type":         device_type,
        "hardware":     hardware,
        "is_duplicate": is_duplicate,
        "timestamp":    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

    return jsonify({
        "status":       "success",
        "is_duplicate": is_duplicate
    }), 200


@app.route('/')
def dashboard():
    duplicate_count = sum(1 for d in devices if d['is_duplicate'])
    fingerprints    = set(d['fingerprint'] for d in devices if d['fingerprint'] != 'N/A')
    unique_count    = len(fingerprints)
    hta_count       = sum(1 for d in devices if d['type'] == 'Windows' and not d['mac'].startswith('Browser-'))
    browser_count   = sum(1 for d in devices if d['mac'].startswith('Browser-'))

    return render_template_string(
        DASHBOARD_HTML,
        devices         = devices,
        count           = len(devices),
        unique_count    = unique_count,
        duplicate_count = duplicate_count,
        hta_count       = hta_count,
        browser_count   = browser_count,
        devices_json    = json.dumps(devices, ensure_ascii=True)
    )


@app.route('/register')
def serve_hta():
    """Serves the .hta file for download — Windows opens it automatically."""
    hta_path = os.path.join(os.path.dirname(__file__), 'register.hta')
    if not os.path.exists(hta_path):
        return "register.hta not found on server", 404
    with open(hta_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return Response(
        content,
        mimetype='application/hta',
        headers={'Content-Disposition': 'attachment; filename="register.hta"'}
    )


@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
