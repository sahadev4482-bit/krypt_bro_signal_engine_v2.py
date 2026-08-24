import os
import threading
import time
import requests

from flask import Flask, jsonify, render_template, request

import signal_engine as eng
import delta_trading as trade
import delta_ws
import analytics_store as analytics
import ai_assistant

app = Flask(__name__)

DELTA_BASE_URL = "https://api.india.delta.exchange"
TICKER_CACHE = {"time": 0.0, "data": {}}
TICKER_CACHE_SECONDS = 4.0

TOKEN_SYMBOLS = [
    "SOL","XRP","BNB","ADA","DOGE","AVAX","LINK","LTC","DOT","TRX",
    "BCH","UNI","ATOM","NEAR","APT","ARB","OP","SUI","FIL","INJ",
    "ETC","AAVE","MKR","RUNE","SEI","TIA","WIF","PEPE","SHIB","TON",
    "ICP","HBAR","FET","RENDER","ALGO","GRT","JUP","BONK","PYTH","ENA",
]

def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _ticker_price(row):
    for key in ("close", "mark_price", "spot_price", "last_price", "price"):
        val = _num(row.get(key))
        if val is not None:
            return val
    return None

def _ticker_move_pct(row):
    # Prefer explicit percentage fields if Delta supplies them.
    for key in (
        "price_change_24h_pct",
        "price_change_percent",
        "change_24h_pct",
        "percent_change_24h",
    ):
        val = _num(row.get(key))
        if val is not None:
            return val

    # Tolerant fallback from current and 24h-open/reference values.
    current = _ticker_price(row)
    if current is None:
        return None

    for key in ("open", "open_24h", "price_24h_ago"):
        base = _num(row.get(key))
        if base not in (None, 0):
            return ((current - base) / base) * 100.0
    return None

def get_public_tickers():
    now = time.time()
    if TICKER_CACHE["data"] and now - TICKER_CACHE["time"] < TICKER_CACHE_SECONDS:
        return TICKER_CACHE["data"]

    try:
        r = requests.get(
            f"{DELTA_BASE_URL}/v2/tickers",
            params={"contract_types": "perpetual_futures"},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("result", []) if isinstance(payload, dict) else []

        mapped = {}
        for row in rows:
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            mapped[symbol] = row

        TICKER_CACHE["time"] = now
        TICKER_CACHE["data"] = mapped
        return mapped
    except Exception:
        app.logger.exception("Delta public ticker fetch failed")
        return TICKER_CACHE["data"]

def token_snapshot():
    tickers = get_public_tickers()
    result = []

    for index, token in enumerate(TOKEN_SYMBOLS):
        # Delta perpetuals commonly use TOKENUSD. Also try TOKENUSDT defensively.
        row = tickers.get(f"{token}USD") or tickers.get(f"{token}USDT")
        price = _ticker_price(row) if row else None
        move = _ticker_move_pct(row) if row else None

        result.append({
            "symbol": token,
            "group": index // 10 + 1,
            "rate": price,
            "move_pct": move,
            "available": row is not None,
            "status": "LIVE" if row is not None else "UNAVAILABLE",
        })

    return result

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
        "active_signals": eng.active_signal_snapshot(),
        "performance": eng.performance_stats(),
        "assets": {
            asset: {
                "enabled": eng.ASSET_ENABLED[asset],
                "latest": eng.LATEST_STATUS[asset],
            }
            for asset in eng.ASSETS
        },
    })


@app.get("/api/signals/history")
def api_signal_history():
    return jsonify({"signals": eng.signal_history(request.args.get("limit", 30)), "performance": eng.performance_stats()})

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


@app.get("/api/tokens")
def api_tokens():
    return jsonify({
        "source": "DELTA",
        "cache_seconds": TICKER_CACHE_SECONDS,
        "tokens": token_snapshot(),
    })


@app.get("/api/trading/status")
def api_trading_status():
    return jsonify(trade.trading_status())

@app.get("/api/positions")
def api_positions():
    try:
        positions = trade.get_positions()
        return jsonify({"success": True, "positions": positions})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "positions": []}), 400

@app.post("/api/order")
def api_order():
    data = request.get_json(silent=True) or {}
    try:
        result = trade.place_market_order(
            product_symbol=data.get("product_symbol"),
            size=data.get("size"),
            side=data.get("side"),
            reduce_only=bool(data.get("reduce_only", False)),
        )
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

@app.post("/api/square-off")
def api_square_off():
    data = request.get_json(silent=True) or {}
    try:
        result = trade.square_off_position(
            product_id=data.get("product_id"),
            product_symbol=data.get("product_symbol"),
            size=data.get("size"),
        )
        return jsonify({"success": True, "result": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

@app.post("/api/square-off-all")
def api_square_off_all():
    try:
        result = trade.square_off_all()
        return jsonify({"success": True, "results": result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400




def _ai_context():
    """
    Sanitized read-only application context.
    Deliberately excludes every credential / secret / token.
    """
    live = delta_ws.snapshot()
    status_data = eng.dashboard_snapshot()
    performance = analytics.summary()

    positions = []
    positions_error = None
    try:
        if trade.credentials_configured():
            positions = trade.get_positions()
    except Exception as exc:
        positions_error = str(exc)[:180]

    safe_positions = []
    for p in positions or []:
        safe_positions.append({
            "product_symbol": p.get("product_symbol"),
            "size": p.get("size"),
            "entry_price": p.get("entry_price"),
            "mark_price": p.get("mark_price"),
            "unrealized_pnl": p.get("unrealized_pnl", p.get("unrealised_pnl")),
        })

    return {
        "live_market": live,
        "signal_engine": status_data,
        "performance": performance,
        "positions": safe_positions,
        "positions_error": positions_error,
        "trading": {
            "credentials_configured": trade.credentials_configured(),
            "execution_enabled": bool(trade.TRADING_ENABLED),
            "ai_execution_permission": False,
        },
        "security": {
            "api_keys_in_context": False,
            "api_secrets_in_context": False,
            "telegram_token_in_context": False,
        },
    }


@app.get("/api/ai/status")
def api_ai_status():
    return jsonify(ai_assistant.status())


@app.post("/api/ai/chat")
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    history = data.get("history") or []

    if not message:
        return jsonify({"success": False, "error": "Message is required."}), 400

    try:
        answer = ai_assistant.ask(
            message=message,
            context=_ai_context(),
            history=history if isinstance(history, list) else [],
        )
        return jsonify({
            "success": True,
            "answer": answer,
            "model": ai_assistant.AI_MODEL,
            "mode": "READ_ONLY",
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

@app.get("/api/performance")
def api_performance():
    return jsonify(analytics.summary())

@app.get("/api/research/trades")
def api_research_trades():
    return jsonify({"trades": analytics.read_trades(limit=1000)})

@app.get("/api/live")
def api_live():
    """Fast in-memory quote endpoint fed by one Delta public WebSocket."""
    return jsonify(delta_ws.snapshot())

def scanner_loop():
    eng.logger.info("Dashboard scanner thread started")
    while True:
        try:
            eng.scan_once()
        except Exception:
            eng.logger.exception("Dashboard scanner loop error")
        time.sleep(eng.SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    delta_ws.start()
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=eng.keep_alive_ping, daemon=True).start()
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)
