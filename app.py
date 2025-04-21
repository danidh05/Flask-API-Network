from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask import render_template

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///network_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ────────────────────────────────────────────
# DATABASE MODELS
# ────────────────────────────────────────────

class CellData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    operator = db.Column(db.String(50))
    signal_power = db.Column(db.Integer)
    snr = db.Column(db.Float)
    network_type = db.Column(db.String(10))
    band = db.Column(db.String(20))
    cell_id = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime)

class DeviceLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(50), unique=True)
    last_seen = db.Column(db.DateTime)

with app.app_context():
    db.create_all()

# ────────────────────────────────────────────
# ROUTES
# ────────────────────────────────────────────

@app.route("/")
def index():
    return "Network Cell Analyzer Backend is Running"

@app.route('/receive-data', methods=['POST'])
def receive_data():
    data = request.get_json()

    try:
        # Extract fields
        operator = data['operator']
        signal_power = int(data['signal_power'])
        snr = float(data.get('snr', 0.0))
        network_type = data['network_type']
        band = data.get('band', "N/A")
        cell_id = data['cell_id']
        timestamp_str = data['timestamp']
        timestamp = datetime.strptime(timestamp_str, "%d %b %Y %I:%M %p")

        # Save to CellData table
        new_entry = CellData(
            operator=operator,
            signal_power=signal_power,
            snr=snr,
            network_type=network_type,
            band=band,
            cell_id=cell_id,
            timestamp=timestamp
        )
        db.session.add(new_entry)

        # Log IP address
        client_ip = request.remote_addr
        now = datetime.utcnow()
        existing_device = DeviceLog.query.filter_by(ip_address=client_ip).first()
        if existing_device:
            existing_device.last_seen = now
        else:
            db.session.add(DeviceLog(ip_address=client_ip, last_seen=now))

        db.session.commit()

        return jsonify({"message": "Data received successfully"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/get-stats', methods=['GET'])
def get_stats():
    try:
        start_str = request.args.get('start')
        end_str = request.args.get('end')

        start_time = datetime.strptime(start_str, "%d %b %Y %I:%M %p")
        end_time = datetime.strptime(end_str, "%d %b %Y %I:%M %p")

        records = CellData.query.filter(CellData.timestamp >= start_time, CellData.timestamp <= end_time).all()

        if not records:
            return jsonify({"message": "No data found in this range"}), 404

        total = len(records)
        operator_counts = {}
        network_counts = {}
        signal_per_network = {}
        snr_per_network = {}
        signal_per_device = {"default_device": []}  # One device for now

        for record in records:
            operator_counts[record.operator] = operator_counts.get(record.operator, 0) + 1
            network_counts[record.network_type] = network_counts.get(record.network_type, 0) + 1

            signal_per_network.setdefault(record.network_type, []).append(record.signal_power)
            snr_per_network.setdefault(record.network_type, []).append(record.snr)
            signal_per_device["default_device"].append(record.signal_power)

        stats = {
            "connectivity_per_operator": {
                k: f"{round(v / total * 100, 2)}%" for k, v in operator_counts.items()
            },
            "connectivity_per_network_type": {
                k: f"{round(v / total * 100, 2)}%" for k, v in network_counts.items()
            },
            "avg_signal_per_network_type": {
                k: round(sum(v) / len(v), 2) for k, v in signal_per_network.items()
            },
            "avg_snr_per_network_type": {
                k: round(sum(v) / len(v), 2) for k, v in snr_per_network.items()
            },
            "avg_signal_per_device": {
                k: round(sum(v) / len(v), 2) for k, v in signal_per_device.items()
            }
        }

        return jsonify(stats), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/central-stats')
def central_stats():
    devices = DeviceLog.query.all()
    device_list = [
        {
            "ip": d.ip_address,
            "last_seen": d.last_seen.strftime("%d %b %Y %I:%M %p")
        } for d in devices
    ]
    return render_template('central_stats.html', total_devices=len(devices), devices=device_list)

# ────────────────────────────────────────────
# RUN
# ────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
