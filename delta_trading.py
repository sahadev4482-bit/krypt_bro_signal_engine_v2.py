import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import requests

BASE_URL = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange").rstrip("/")
API_KEY = os.getenv("DELTA_API_KEY", "").strip()
API_SECRET = os.getenv("DELTA_API_SECRET", "").strip()
TRADING_ENABLED = os.getenv("DELTA_TRADING_ENABLED", "false").lower() == "true"

USER_AGENT = "KRYPT-BRO/1.0"

class DeltaTradingError(RuntimeError):
    pass

def credentials_configured():
    return bool(API_KEY and API_SECRET)

def trading_status():
    return {
        "credentials_configured": credentials_configured(),
        "trading_enabled": TRADING_ENABLED,
        "base_url": BASE_URL,
    }

def _compact_json(payload):
    if payload is None:
        return ""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

def _signed_headers(method, path, query_string="", body=""):
    if not credentials_configured():
        raise DeltaTradingError("Delta API credentials are not configured in Render.")

    timestamp = str(int(time.time()))
    query_part = f"?{query_string}" if query_string else ""
    signature_data = f"{method.upper()}{timestamp}{path}{query_part}{body}"

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        signature_data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "api-key": API_KEY,
        "signature": signature,
        "timestamp": timestamp,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def signed_request(method, path, params=None, payload=None, timeout=12):
    params = params or {}
    # Important: the signed query string must match the actual request query.
    query_string = urlencode(params, doseq=True)
    body = _compact_json(payload)

    headers = _signed_headers(method, path, query_string, body)
    url = f"{BASE_URL}{path}"

    response = requests.request(
        method=method.upper(),
        url=url,
        params=params if params else None,
        data=body if body else None,
        headers=headers,
        timeout=timeout,
    )

    try:
        data = response.json()
    except Exception:
        data = {"success": False, "error": {"code": "invalid_json", "message": response.text[:300]}}

    if not response.ok or not data.get("success", False):
        raise DeltaTradingError(
            f"Delta API error {response.status_code}: {data.get('error', data)}"
        )
    return data

def get_positions():
    data = signed_request("GET", "/v2/positions/margined")
    result = data.get("result") or []
    return result if isinstance(result, list) else [result]

def place_market_order(product_symbol, size, side, reduce_only=False):
    if not TRADING_ENABLED:
        raise DeltaTradingError("Live trading is disabled. Set DELTA_TRADING_ENABLED=true in Render.")

    side = str(side).lower().strip()
    if side not in ("buy", "sell"):
        raise DeltaTradingError("side must be buy or sell")

    size = int(size)
    if size <= 0:
        raise DeltaTradingError("size must be a positive integer")

    product_symbol = str(product_symbol).strip().upper()
    if not product_symbol:
        raise DeltaTradingError("product_symbol is required")

    payload = {
        "product_symbol": product_symbol,
        "size": size,
        "order_type": "market_order",
        "side": side,
        "reduce_only": bool(reduce_only),
    }

    return signed_request("POST", "/v2/orders", payload=payload).get("result")

def square_off_position(product_id, product_symbol, size):
    if not TRADING_ENABLED:
        raise DeltaTradingError("Live trading is disabled. Set DELTA_TRADING_ENABLED=true in Render.")

    signed_size = int(size)
    if signed_size == 0:
        return {"message": "Position already flat"}

    side = "sell" if signed_size > 0 else "buy"

    payload = {
        "product_id": int(product_id),
        "size": abs(signed_size),
        "order_type": "market_order",
        "side": side,
        "reduce_only": True,
    }
    return signed_request("POST", "/v2/orders", payload=payload).get("result")

def square_off_all():
    positions = get_positions()
    results = []

    for pos in positions:
        try:
            size = int(pos.get("size") or 0)
        except Exception:
            size = 0

        if size == 0:
            continue

        try:
            order = square_off_position(
                product_id=pos.get("product_id"),
                product_symbol=pos.get("product_symbol"),
                size=size,
            )
            results.append({
                "success": True,
                "product_symbol": pos.get("product_symbol"),
                "result": order,
            })
        except Exception as exc:
            results.append({
                "success": False,
                "product_symbol": pos.get("product_symbol"),
                "error": str(exc),
            })

    return results
