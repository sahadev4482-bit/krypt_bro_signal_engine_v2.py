import json
import logging
import threading
import time
from datetime import datetime, timezone

import websocket

logger = logging.getLogger("krypt_bro.delta_ws")

WS_URL = "wss://public-socket.india.delta.exchange"
SYMBOL_TO_ASSET = {
    "BTCUSD": "BTC",
    "ETHUSD": "ETH",
    "PAXGUSD": "GOLD",
}
SYMBOLS = list(SYMBOL_TO_ASSET.keys())

_lock = threading.RLock()
_state = {
    "connected": False,
    "last_message_at": None,
    "last_error": None,
    "reconnects": 0,
    "quotes": {
        asset: {
            "asset": asset,
            "symbol": symbol,
            "price": None,
            "timestamp": None,
            "source": "DELTA_WS_TRADES",
            "sequence": 0,
        }
        for symbol, asset in SYMBOL_TO_ASSET.items()
    },
}

_started = False


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def snapshot():
    with _lock:
        return {
            "connected": bool(_state["connected"]),
            "last_message_at": _state["last_message_at"],
            "last_error": _state["last_error"],
            "reconnects": _state["reconnects"],
            "quotes": {k: dict(v) for k, v in _state["quotes"].items()},
        }


def _first_number(obj, keys):
    for key in keys:
        try:
            value = obj.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError, AttributeError):
            pass
    return None


def _extract_symbol(obj):
    for key in ("symbol", "product_symbol", "s"):
        value = obj.get(key) if isinstance(obj, dict) else None
        if value:
            return str(value).upper()
    product = obj.get("product") if isinstance(obj, dict) else None
    if isinstance(product, dict):
        value = product.get("symbol")
        if value:
            return str(value).upper()
    return None


def _handle_trade_message(payload):
    """
    Delta's trades channel can evolve in envelope shape. Accept both a direct
    event object and common nested data/result structures.
    """
    candidates = []
    if isinstance(payload, dict):
        candidates.append(payload)
        for key in ("data", "result", "trade"):
            value = payload.get(key)
            if isinstance(value, dict):
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(x for x in value if isinstance(x, dict))
    elif isinstance(payload, list):
        candidates.extend(x for x in payload if isinstance(x, dict))

    updated = False
    for item in candidates:
        symbol = _extract_symbol(item)
        if symbol not in SYMBOL_TO_ASSET:
            continue

        price = _first_number(
            item,
            ("price", "fill_price", "trade_price", "last_price", "close", "p"),
        )
        if price is None or price <= 0:
            continue

        asset = SYMBOL_TO_ASSET[symbol]
        with _lock:
            q = _state["quotes"][asset]
            q["price"] = price
            q["timestamp"] = _utc_iso()
            q["sequence"] = int(q.get("sequence", 0)) + 1
            _state["last_message_at"] = q["timestamp"]
        updated = True

        # Tick-level lifecycle tracking. Do NOT run the full strategy here.
        try:
            from backend import signal_engine as eng
            eng.update_active_signal(asset, price)
        except Exception:
            logger.exception("Tick lifecycle update failed for %s", asset)

    return updated


def _on_open(ws):
    with _lock:
        _state["connected"] = True
        _state["last_error"] = None

    subscribe = {
        "type": "subscribe",
        "payload": {
            "channels": [
                {
                    "name": "trades",
                    "symbols": SYMBOLS,
                }
            ]
        },
    }
    ws.send(json.dumps(subscribe))
    logger.info("Delta public WebSocket connected | trades=%s", ",".join(SYMBOLS))


def _on_message(ws, message):
    try:
        payload = json.loads(message)
    except Exception:
        return

    msg_type = payload.get("type") if isinstance(payload, dict) else None

    # Delta application-level ping/pong support.
    if msg_type == "ping":
        try:
            ws.send(json.dumps({"type": "pong"}))
        except Exception:
            pass
        return

    _handle_trade_message(payload)


def _on_error(ws, error):
    with _lock:
        _state["last_error"] = str(error)[:300]
    logger.warning("Delta WebSocket error: %s", error)


def _on_close(ws, code, message):
    with _lock:
        _state["connected"] = False
    logger.warning("Delta WebSocket closed | code=%s msg=%s", code, message)


def _runner():
    backoff = 2
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            # Protocol ping every 25 sec; pong timeout protects stale sockets.
            ws.run_forever(ping_interval=25, ping_timeout=8)
        except Exception as exc:
            with _lock:
                _state["last_error"] = str(exc)[:300]
            logger.exception("Delta WebSocket runner failed")

        with _lock:
            _state["connected"] = False
            _state["reconnects"] += 1

        time.sleep(backoff)
        backoff = min(backoff * 2, 30)


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_runner, daemon=True, name="delta-public-ws").start()
