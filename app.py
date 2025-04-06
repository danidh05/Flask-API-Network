from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///network_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Database model
class CellData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    operator = db.Column(db.String(50))
    signal_power = db.Column(db.Integer)
    snr = db.Column(db.Float)
    network_type = db.Column(db.String(10))
    band = db.Column(db.String(20))
    cell_id = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime)

# Initialize the database
with app.app_context():
    db.create_all()

# Test route
@app.route("/")
def index():
    return "Network Cell Analyzer Backend is Running"

# POST endpoint to receive data
@app.route('/receive-data', methods=['POST'])
def receive_data():
    data = request.get_json()

    try:
        # Extract data from request
        operator = data['operator']
        signal_power = int(data['signal_power'])
        snr = float(data.get('snr', 0.0))  # Optional
        network_type = data['network_type']
        band = data.get('band', "N/A")
        cell_id = data['cell_id']
        timestamp_str = data['timestamp']

        # Convert timestamp
        timestamp = datetime.strptime(timestamp_str, "%d %b %Y %I:%M %p")

        # Create DB record
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
        db.session.commit()

        return jsonify({"message": "Data received successfully"}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# GET endpoint to return statistics between two timestamps
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

        # Grouping & Averages
        operator_counts = {}
        network_counts = {}
        signal_per_network = {}
        snr_per_network = {}
        signal_per_device = {}  # Assuming all from one device for now

        for record in records:
            # Count by operator
            operator_counts[record.operator] = operator_counts.get(record.operator, 0) + 1

            # Count by network type
            network_counts[record.network_type] = network_counts.get(record.network_type, 0) + 1

            # Avg signal power per network type
            if record.network_type not in signal_per_network:
                signal_per_network[record.network_type] = []
            signal_per_network[record.network_type].append(record.signal_power)

            # Avg SNR per network type
            if record.network_type not in snr_per_network:
                snr_per_network[record.network_type] = []
            snr_per_network[record.network_type].append(record.snr)

            # Avg signal per device (we'll just assume 1 device, otherwise add a device_id field)
            signal_per_device.setdefault("default_device", []).append(record.signal_power)

        # Format final results
        stats = {
            "connectivity_per_operator": {
                k: f"{round(v / total * 100, 2)}%" for k, v in operator_counts.items()
            },
            "connectivity_per_network_type": {
                k: f"{round(v / total * 100, 2)}%" for k, v in network_counts.items()
            },
            "avg_signal_per_network_type": {
                k: round(sum(v)/len(v), 2) for k, v in signal_per_network.items()
            },
            "avg_snr_per_network_type": {
                k: round(sum(v)/len(v), 2) for k, v in snr_per_network.items()
            },
            "avg_signal_per_device": {
                k: round(sum(v)/len(v), 2) for k, v in signal_per_device.items()
            }
        }

        return jsonify(stats), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
