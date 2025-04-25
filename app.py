"""
network_backend.py
──────────────────────────────────────────────
Flask backend for the Network Cell Analyzer
• Stores per-device LTE metrics
• Returns per-device or cross-device statistics
• Auto-migrates the DB to add `device_id` column if missing
"""

from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz

# ───────────────────────────────────────
# CONFIG
# ───────────────────────────────────────
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///network_data.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
lebanon_tz = pytz.timezone("Asia/Beirut")

# ───────────────────────────────────────
# MODELS
# ───────────────────────────────────────
class CellData(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    device_id    = db.Column(db.String(64), index=True)      # <-- NEW
    operator     = db.Column(db.String(50))
    signal_power = db.Column(db.Integer)
    snr          = db.Column(db.Float)
    network_type = db.Column(db.String(10))
    band         = db.Column(db.String(20))
    cell_id      = db.Column(db.String(50))
    timestamp    = db.Column(db.DateTime, index=True)

class DeviceLog(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(50), unique=True)
    last_seen  = db.Column(db.DateTime)

# ───────────────────────────────────────
# DB INITIALISATION & SELF-MIGRATION
# ───────────────────────────────────────
with app.app_context():
    db.create_all()

    # If the user forgot to run ALTER TABLE, add device_id automatically
    col_names = [
        row[1]
        for row in db.session.execute("PRAGMA table_info(cell_data)").fetchall()
    ]
    if "device_id" not in col_names:
        db.session.execute("ALTER TABLE cell_data ADD COLUMN device_id VARCHAR(64)")
        db.session.commit()
        print("➕  Added missing column `device_id` to cell_data")

# ───────────────────────────────────────
# ROUTES
# ───────────────────────────────────────
@app.route("/")
def index():
    return "📡 Network Cell Analyzer backend is running."

# ---------- RECEIVE DATA ----------
@app.route("/receive-data", methods=["POST"])
def receive_data():
    data = request.get_json(force=True)
    try:
        device_id     = data["device_id"]                 # required
        operator      = data["operator"]
        signal_power  = int(data["signal_power"])
        network_type  = data["network_type"]
        cell_id       = data["cell_id"]
        ts_local      = lebanon_tz.localize(
            datetime.strptime(data["timestamp"], "%d %b %Y %I:%M %p")
        )
        ts_utc        = ts_local.astimezone(pytz.utc)

        band = data.get("band", "N/A")
        snr  = float(data.get("snr", 0.0))

        db.session.add(
            CellData(
                device_id=device_id,
                operator=operator,
                signal_power=signal_power,
                snr=snr,
                network_type=network_type,
                band=band,
                cell_id=cell_id,
                timestamp=ts_utc,
            )
        )

        # update “online devices” table (dashboard)
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0]
        now_utc   = datetime.utcnow()
        dev = DeviceLog.query.filter_by(ip_address=client_ip).first()
        if dev:
            dev.last_seen = now_utc
        else:
            db.session.add(DeviceLog(ip_address=client_ip, last_seen=now_utc))

        db.session.commit()
        return jsonify({"message": "Data received"}), 201

    except KeyError as miss:
        return jsonify({"error": f"Missing field {miss}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---------- PER-DEVICE STATS ----------
@app.route("/get-stats")
def get_stats():
    try:
        device_id = request.args.get("device_id")
        if not device_id:
            return jsonify({"error": "device_id is required"}), 400

        # --- date parsing
        s, e = request.args.get("start"), request.args.get("end")
        first = db.session.query(db.func.min(CellData.timestamp)).scalar()
        last  = db.session.query(db.func.max(CellData.timestamp)).scalar()
        if first is None:
            return jsonify({"message": "No data"}), 404

        def to_utc(date_str, default):
            if not date_str:
                return default
            return lebanon_tz.localize(
                datetime.strptime(date_str, "%d %b %Y %I:%M %p")
            ).astimezone(pytz.utc)

        start_utc, end_utc = to_utc(s, first), to_utc(e, last)
        if end_utc < start_utc:
            return jsonify({"error": "End date must be after start date"}), 400

        rows = (
            CellData.query.filter_by(device_id=device_id)
            .filter(CellData.timestamp.between(start_utc, end_utc))
            .all()
        )
        if not rows:
            return jsonify({"message": "No data for device"}), 404

        # --- aggregation
        total = len(rows)
        op_cnt, net_cnt, sig_net, snr_net = {}, {}, {}, {}
        sig_device = []
        for r in rows:
            op_cnt[r.operator] = op_cnt.get(r.operator, 0) + 1
            net_cnt[r.network_type] = net_cnt.get(r.network_type, 0) + 1
            sig_net.setdefault(r.network_type, []).append(r.signal_power)
            snr_net.setdefault(r.network_type, []).append(r.snr)
            sig_device.append(r.signal_power)

        return jsonify(
            {
                "connectivity_per_operator": {
                    k: f"{round(v/total*100,2)}%" for k, v in op_cnt.items()
                },
                "connectivity_per_network_type": {
                    k: f"{round(v/total*100,2)}%" for k, v in net_cnt.items()
                },
                "avg_signal_per_network_type": {
                    k: round(sum(v)/len(v), 2) for k, v in sig_net.items()
                },
                "avg_snr_per_network_type": {
                    k: round(sum(v)/len(v), 2) for k, v in snr_net.items()
                },
                "avg_signal_device": round(sum(sig_device)/len(sig_device), 2),
            }
        ), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---------- CROSS-DEVICE AVERAGES ----------
@app.route("/get-stats/avg-all")
def avg_all():
    try:
        s, e = request.args.get("start"), request.args.get("end")
        first = db.session.query(db.func.min(CellData.timestamp)).scalar()
        last  = db.session.query(db.func.max(CellData.timestamp)).scalar()
        if first is None:
            return jsonify({"message": "No data"}), 404

        start_utc = first if not s else lebanon_tz.localize(
            datetime.strptime(s, "%d %b %Y %I:%M %p")
        ).astimezone(pytz.utc)
        end_utc   = last  if not e else lebanon_tz.localize(
            datetime.strptime(e, "%d %b %Y %I:%M %p")
        ).astimezone(pytz.utc)

        if end_utc < start_utc:
            return jsonify({"error": "End date must be after start date"}), 400

        avg_sig, avg_snr = (
            CellData.query.with_entities(
                db.func.avg(CellData.signal_power),
                db.func.avg(CellData.snr),
            )
            .filter(CellData.timestamp.between(start_utc, end_utc))
            .first()
        )
        return (
            jsonify(
                {
                    "avg_signal_all_devices": round(avg_sig or 0, 2),
                    "avg_snr_all_devices": round(avg_snr or 0, 2),
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---------- DASHBOARD (unchanged) ----------
@app.route("/central-stats")
def central_stats():
    devices = DeviceLog.query.all()
    device_list = [
        {
            "ip": d.ip_address,
            "last_seen": d.last_seen.astimezone(lebanon_tz).strftime(
                "%d %b %Y %I:%M %p"
            ),
        }
        for d in devices
    ]
    return render_template(
        "central_stats.html", total_devices=len(devices), devices=device_list
    )

# ───────────────────────────────────────
# MAIN
# ───────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
