from flask import Flask, request, jsonify, render_template_string
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
        th { background: #00d4ff; color: #000; padding: 12px 10px; text-align: left; font-size: 12px; white-space: nowrap; }
        td { padding: 10px; border-bottom: 1px solid #222; font-size: 12px; word-break: break-all; }
        tr:hover { background: #16213e; }
        .duplicate { background: #ff000022; }
        .fingerprint { color: #00d4ff; font-family: monospace; font-size: 11px; }
        .detail-btn { background: #00d4ff; color: #000; border: none; padding: 4px 10px;
                      border-radius: 5px; cursor: pointer; font-size: 11px; }

        /* ---- type badges ---- */
        .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
                 font-size: 10px; font-weight: bold; white-space: nowrap; }
        .badge-wifi     { background: #00d4ff22; color: #00d4ff; border: 1px solid #00d4ff55; }
        .badge-ethernet { background: #00ff8822; color: #00ff88; border: 1px solid #00ff8855; }
        .badge-vpn      { background: #ff990022; color: #ff9900; border: 1px solid #ff990055; }
        .badge-virtual  { background: #aa44ff22; color: #bb66ff; border: 1px solid #aa44ff55; }
        .badge-other    { background: #88888822; color: #aaa;    border: 1px solid #88888855; }

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
                        display: flex; align-items: center; gap: 8px; }
        .adapter-detail { color: #aaa; font-size: 11px; margin: 2px 0; font-family: monospace; }
        .adapter-detail span { color: #eee; }
        .close-btn { background: #ff6b6b; color: #fff; border: none; padding: 8px 20px;
                     border-radius: 5px; cursor: pointer; margin-top: 15px; width: 100%; font-size: 14px; }
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
            <td>{{ d.mac }}</td>
            <td>{{ d.hardware.cpu_id if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.board_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.bios_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.disk_serial if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.system_uuid if d.hardware else 'N/A' }}</td>
            <td><span class="fingerprint">{{ d.fingerprint[:16] }}...</span></td>
            <td>{{ d.hardware.local_ip if d.hardware else 'N/A' }}</td>
            <td>{{ d.hardware.public_ip if d.hardware else 'N/A' }}</td>
            <td>{{ '⚠️ YES' if d.is_duplicate else '✅ No' }}</td>
            <td>{{ d.timestamp }}</td>
            <td><button class="detail-btn" onclick="showDetail({{ loop.index0 }})">View</button></td>
        </tr>
        {% endfor %}
    </table>

    <div class="modal" id="modal">
        <div class="modal-content">
            <h2>📋 Full Device Details</h2>
            <div id="modal-body"></div>
            <button class="close-btn" onclick="closeModal()">✕ Close</button>
        </div>
    </div>

    <script>
        var devices = {{ devices_json }};

        function val(v) { return (v !== null && v !== undefined && v !== '') ? v : 'N/A'; }

        /* Render a coloured type badge */
        function typeBadge(type) {
            var cls = {
                'WiFi':     'badge-wifi',
                'Ethernet': 'badge-ethernet',
                'VPN':      'badge-vpn',
                'Virtual':  'badge-virtual'
            }[type] || 'badge-other';
            return '<span class="badge ' + cls + '">' + val(type) + '</span>';
        }

        function showDetail(index) {
            var d = devices[index];
            var hw = d.hardware || {};
            var html = '<table class="modal-table">';

            // System
            html += '<tr><td colspan="2" class="section-header">🖥️ SYSTEM</td></tr>';
            html += '<tr><td>Hostname</td><td>' + val(d.hostname) + '</td></tr>';
            html += '<tr><td>OS</td><td>' + val(hw.os) + '</td></tr>';
            html += '<tr><td>Manufacturer</td><td>' + val(hw.system_manufacturer) + '</td></tr>';
            html += '<tr><td>Model</td><td>' + val(hw.system_model) + '</td></tr>';
            html += '<tr><td>System Serial</td><td>' + val(hw.system_serial) + '</td></tr>';
            html += '<tr><td>System UUID</td><td>' + val(hw.system_uuid) + '</td></tr>';

            // Network summary
            html += '<tr><td colspan="2" class="section-header">🌐 NETWORK</td></tr>';
            html += '<tr><td>WiFi MAC</td><td>' + val(d.mac) + '</td></tr>';
            html += '<tr><td>Local IP</td><td>' + val(hw.local_ip) + '</td></tr>';
            html += '<tr><td>Public IP</td><td>' + val(hw.public_ip) + '</td></tr>';
            html += '</table>';

            // All Adapters — now with DNS + type badge
            html += '<div style="margin-top:10px">';
            html += '<div class="section-header" style="margin-bottom:8px">📡 ALL NETWORK ADAPTERS</div>';
            if (hw.all_adapters && hw.all_adapters.length > 0) {
                hw.all_adapters.forEach(function(a) {
                    html += '<div class="adapter-block">';
                    html += '<div class="adapter-name">🔌 ' + val(a.name) + ' ' + typeBadge(a.adapter_type) + '</div>';
                    html += '<div class="adapter-detail">MAC Address:  <span>' + val(a.mac)         + '</span></div>';
                    html += '<div class="adapter-detail">IP Address:   <span>' + val(a.ip)          + '</span></div>';
                    html += '<div class="adapter-detail">Subnet Mask:  <span>' + val(a.subnet)      + '</span></div>';
                    html += '<div class="adapter-detail">Gateway:      <span>' + val(a.gateway)     + '</span></div>';
                    html += '<div class="adapter-detail">DHCP Enabled: <span>' + val(a.dhcp)        + '</span></div>';
                    html += '<div class="adapter-detail">DHCP Server:  <span>' + val(a.dhcp_server) + '</span></div>';
                    html += '<div class="adapter-detail">DNS Servers:  <span>' + val(a.dns_servers) + '</span></div>';
                    html += '</div>';
                });
            } else {
                html += '<div style="color:#888;padding:10px">No adapters found</div>';
            }
            html += '</div>';

            // Bluetooth
            html += '<div style="margin-top:10px">';
            html += '<div class="section-header" style="margin-bottom:8px">📶 BLUETOOTH ADAPTERS</div>';
            if (hw.bluetooth_adapters && hw.bluetooth_adapters.length > 0) {
                hw.bluetooth_adapters.forEach(function(b) {
                    html += '<div class="adapter-block">';
                    html += '<div class="adapter-name">🔵 ' + val(b.name) + '</div>';
                    html += '<div class="adapter-detail">Manufacturer: <span>' + val(b.manufacturer) + '</span></div>';
                    html += '<div class="adapter-detail">Device ID:    <span>' + val(b.device_id)    + '</span></div>';
                    html += '</div>';
                });
            } else {
                html += '<div style="color:#888;padding:10px">No Bluetooth adapters found</div>';
            }
            html += '</div>';

            html += '<table class="modal-table" style="margin-top:10px">';

            // CPU
            html += '<tr><td colspan="2" class="section-header">⚙️ CPU</td></tr>';
            html += '<tr><td>CPU Name</td><td>'      + val(hw.cpu_name)    + '</td></tr>';
            html += '<tr><td>CPU ID</td><td>'        + val(hw.cpu_id)      + '</td></tr>';
            html += '<tr><td>Cores / Threads</td><td>' + val(hw.cpu_cores) + ' / ' + val(hw.cpu_threads) + '</td></tr>';
            html += '<tr><td>Max Speed</td><td>'     + val(hw.cpu_speed)   + ' MHz</td></tr>';

            // Motherboard
            html += '<tr><td colspan="2" class="section-header">🔲 MOTHERBOARD</td></tr>';
            html += '<tr><td>Manufacturer</td><td>'  + val(hw.board_manufacturer) + '</td></tr>';
            html += '<tr><td>Product</td><td>'       + val(hw.board_product)      + '</td></tr>';
            html += '<tr><td>Version</td><td>'       + val(hw.board_version)      + '</td></tr>';
            html += '<tr><td>Serial</td><td>'        + val(hw.board_serial)       + '</td></tr>';

            // BIOS
            html += '<tr><td colspan="2" class="section-header">💾 BIOS</td></tr>';
            html += '<tr><td>Manufacturer</td><td>'  + val(hw.bios_manufacturer) + '</td></tr>';
            html += '<tr><td>Version</td><td>'       + val(hw.bios_version)      + '</td></tr>';
            html += '<tr><td>Serial</td><td>'        + val(hw.bios_serial)       + '</td></tr>';
            html += '<tr><td>Date</td><td>'          + val(hw.bios_date)         + '</td></tr>';

            // Disk
            html += '<tr><td colspan="2" class="section-header">💿 DISK</td></tr>';
            html += '<tr><td>Model</td><td>'   + val(hw.disk_model)  + '</td></tr>';
            html += '<tr><td>Serial</td><td>'  + val(hw.disk_serial) + '</td></tr>';
            html += '<tr><td>Size</td><td>'    + val(hw.disk_size)   + ' GB</td></tr>';

            // RAM
            html += '<tr><td colspan="2" class="section-header">🧠 RAM</td></tr>';
            html += '<tr><td>Manufacturer</td><td>'  + val(hw.ram_manufacturer) + '</td></tr>';
            html += '<tr><td>Serial</td><td>'        + val(hw.ram_serial)       + '</td></tr>';
            html += '<tr><td>Speed</td><td>'         + val(hw.ram_speed)        + ' MHz</td></tr>';
            html += '<tr><td>Capacity</td><td>'      + val(hw.ram_capacity)     + ' GB</td></tr>';

            // GPU
            html += '<tr><td colspan="2" class="section-header">🎮 GPU</td></tr>';
            html += '<tr><td>Name</td><td>'    + val(hw.gpu_name)   + '</td></tr>';
            html += '<tr><td>Driver</td><td>'  + val(hw.gpu_driver) + '</td></tr>';
            html += '<tr><td>VRAM</td><td>'    + val(hw.gpu_ram)    + ' GB</td></tr>';

            // Security
            html += '<tr><td colspan="2" class="section-header">🔐 SECURITY</td></tr>';
            html += '<tr><td>Fingerprint</td><td>'    + val(d.fingerprint)  + '</td></tr>';
            html += '<tr><td>Duplicate</td><td>'      + (d.is_duplicate ? '⚠️ YES — Same device registered before' : '✅ No') + '</td></tr>';
            html += '<tr><td>Registered At</td><td>'  + val(d.timestamp)   + '</td></tr>';

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

@app.route('/register-device', methods=['POST'])
def register_device():
    data = request.json
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

    return render_template_string(DASHBOARD_HTML,
        devices      = devices,
        count        = len(devices),
        unique_count = unique_count,
        duplicate_count = duplicate_count,
        devices_json = json.dumps(devices))

@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
