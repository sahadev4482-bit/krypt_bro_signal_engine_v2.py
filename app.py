import os
import threading
import time

from flask import Flask, jsonify, render_template

import signal_engine as eng

app = Flask(__name__)

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/health")
def health():
    return "KRYPT BRO: RUNNING", 200

@app.get("/api/status")
def api_status():
    return jsonify({
        "scanner_enabled": eng.SCANNER_ENABLED,
        "telegram_enabled": eng.TELEGRAM_ENABLED,
        "min_rr": eng.MIN_RR,
        "assets": {
            asset: {
                "enabled": eng.ASSET_ENABLED[asset],
                "latest": eng.LATEST_STATUS[asset],
            }
            for asset in eng.ASSETS
        },
    })

@app.post("/api/toggle-scanner")
def toggle_scanner():
    eng.SCANNER_ENABLED = not eng.SCANNER_ENABLED
    return jsonify({"scanner_enabled": eng.SCANNER_ENABLED})

@app.post("/api/toggle-telegram")
def toggle_telegram():
    eng.TELEGRAM_ENABLED = not eng.TELEGRAM_ENABLED
    return jsonify({"telegram_enabled": eng.TELEGRAM_ENABLED})

@app.post("/api/toggle-asset/<asset>")
def toggle_asset(asset):
    asset = asset.upper()
    if asset not in eng.ASSET_ENABLED:
        return jsonify({"error": "Unknown asset"}), 404
    eng.ASSET_ENABLED[asset] = not eng.ASSET_ENABLED[asset]
    return jsonify({"asset": asset, "enabled": eng.ASSET_ENABLED[asset]})

def scanner_loop():
    eng.logger.info("Dashboard scanner thread started")
    while True:
        try:
            eng.scan_once()
        except Exception:
            eng.logger.exception("Dashboard scanner loop error")
        time.sleep(eng.SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=eng.keep_alive_ping, daemon=True).start()
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)
