# KRYPT BRO SIGNAL ENGINE v3 - DELTA ONLY + GOLD + LOW LOAD
# Pure signal generation first.
# Includes: Daily + 4H + 5M Fib R1-R5/S1-S5, 4H/1H/15M/5M MTF,
# closed-candle checks, stale-data rejection, ATR/EMA extension filters,
# directional Fib context, minimum R:R, cooldown and Telegram ON/OFF.
#
import os
import time
import math
import logging
import json
import http.server
import socketserver
import threading
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests

# ============================================================
# KRYPT BRO - PURE SIGNAL GENERATOR
# No order placement. No leverage. No exchange trading API.
# Data: Delta Exchange India public market data
# Alerts: Telegram (optional)
# ============================================================

ASSETS = ["BTC", "ETH", "GOLD"]

DELTA_SYMBOLS = {
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
    "GOLD": "PAXGUSD",
}

INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "1d": 86400,
    "1w": 604800,
}
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "20"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MIN_SIGNAL_SCORE = int(os.getenv("MIN_SIGNAL_SCORE", "70"))
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "600"))

# Scanner / Telegram runtime controls
SCANNER_ENABLED = True
TELEGRAM_ENABLED = True

# Signal quality safeguards
MIN_RR = float(os.getenv("MIN_RR", "1.80"))
MAX_SIGNAL_AGE_SECONDS = int(os.getenv("MAX_SIGNAL_AGE_SECONDS", "360"))
MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", "0.08"))
MAX_ATR_PCT = float(os.getenv("MAX_ATR_PCT", "2.50"))
MAX_EMA_EXTENSION_ATR = float(os.getenv("MAX_EMA_EXTENSION_ATR", "1.50"))
REQUIRE_VOLUME_FOR_SIGNAL = os.getenv("REQUIRE_VOLUME_FOR_SIGNAL", "true").lower() == "true"
SIGNAL_EXPIRY_CANDLES = int(os.getenv("SIGNAL_EXPIRY_CANDLES", "3"))
BREAKOUT_LOOKBACK = int(os.getenv("BREAKOUT_LOOKBACK", "6"))
RETEST_TOLERANCE_ATR = float(os.getenv("RETEST_TOLERANCE_ATR", "0.35"))
JOURNAL_FILE = os.getenv("JOURNAL_FILE", "signal_journal.jsonl")

# Fib confluence tolerance as % of price
FIB_NEAR_PCT = float(os.getenv("FIB_NEAR_PCT", "0.20"))

# Volume confirmation
VOLUME_MULTIPLIER = float(os.getenv("VOLUME_MULTIPLIER", "1.05"))

# ATR-based risk
ATR_SL_MULTIPLIER = float(os.getenv("ATR_SL_MULTIPLIER", "1.20"))

# Strategy polish v2.1 (confirmation-only additions; scanner/runtime flow unchanged)
ADX_PERIOD = int(os.getenv("ADX_PERIOD", "14"))
ADX_TREND_MIN = float(os.getenv("ADX_TREND_MIN", "20"))
WILLIAMS_PERIOD = int(os.getenv("WILLIAMS_PERIOD", "14"))

# TRUE SCALP v2.5: faster 5M entries while preserving hard risk/trigger guards.
# DAILY_MIN_SIGNAL_TARGET is a soft target only; the engine never fabricates a trade.
DAILY_MIN_SIGNAL_TARGET = int(os.getenv("DAILY_MIN_SIGNAL_TARGET", "4"))
ADAPTIVE_MIN_SCORE = int(os.getenv("ADAPTIVE_MIN_SCORE", "67"))
ADAPTIVE_START_HOUR_IST = int(os.getenv("ADAPTIVE_START_HOUR_IST", "10"))
VOLUME_MISSING_PENALTY = int(os.getenv("VOLUME_MISSING_PENALTY", "4"))
CHOPPY_PENALTY = int(os.getenv("CHOPPY_PENALTY", "3"))
OVEREXTENDED_PENALTY = int(os.getenv("OVEREXTENDED_PENALTY", "5"))
EXTREME_EXTENSION_ATR = float(os.getenv("EXTREME_EXTENSION_ATR", "2.60"))
RETEST_BYPASS_SCORE = int(os.getenv("RETEST_BYPASS_SCORE", "80"))
RETEST_BYPASS_AFTER_CANDLES = int(os.getenv("RETEST_BYPASS_AFTER_CANDLES", "1"))
REQUIRE_5M_TRIGGER = os.getenv("REQUIRE_5M_TRIGGER", "true").lower() == "true"

OPTION_MIN_EXPIRY_HOURS = float(os.getenv("OPTION_MIN_EXPIRY_HOURS", "2.0"))
OPTION_MAX_SPREAD_PCT = float(os.getenv("OPTION_MAX_SPREAD_PCT", "12.0"))
OPTION_TARGET_DELTA_MIN = float(os.getenv("OPTION_TARGET_DELTA_MIN", "0.30"))
OPTION_TARGET_DELTA_MAX = float(os.getenv("OPTION_TARGET_DELTA_MAX", "0.72"))
OPTION_CHAIN_TIMEOUT = float(os.getenv("OPTION_CHAIN_TIMEOUT", "10"))

# Delta option-chain underlying names. GOLD is tried defensively across the
# currently listed tokenised-gold underlyings so an unavailable alias never
# interrupts the core BTC/ETH/GOLD signal scanner.
OPTION_UNDERLYINGS = {
    "BTC": ["BTC"],
    "ETH": ["ETH"],
    "GOLD": ["PAXG", "XAUT", "GOLD"],
}

DELTA_BASE_URL = "https://api.india.delta.exchange"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
from backend import analytics_store as analytics

logger = logging.getLogger("krypt_bro")

LAST_SIGNAL = {asset: {"side": None, "time": 0} for asset in ASSETS}

# Full strategy runs only once per newly closed 5-minute candle.
# This drastically reduces REST load compared with recalculating all
# 1D/1H/15M/5M data every 20 seconds.
LAST_PROCESSED_5M_CLOSE = {asset: None for asset in ASSETS}
PENDING_SIGNALS = {asset: None for asset in ASSETS}

# Entry-signal count is used only for a mild late-day threshold relaxation.
# It does not force a signal and resets automatically on the IST calendar day.
DAILY_SIGNAL_STATS = {"date": None, "count": 0}

def _refresh_daily_signal_stats() -> None:
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    if DAILY_SIGNAL_STATS.get("date") != today:
        DAILY_SIGNAL_STATS["date"] = today
        DAILY_SIGNAL_STATS["count"] = 0

def effective_signal_threshold() -> int:
    _refresh_daily_signal_stats()
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    if DAILY_SIGNAL_STATS["count"] >= DAILY_MIN_SIGNAL_TARGET:
        return MIN_SIGNAL_SCORE
    if now_ist.hour < ADAPTIVE_START_HOUR_IST:
        return MIN_SIGNAL_SCORE
    return max(ADAPTIVE_MIN_SCORE, MIN_SIGNAL_SCORE - 3)

def record_entry_signal_sent() -> None:
    _refresh_daily_signal_stats()
    DAILY_SIGNAL_STATS["count"] += 1

ASSET_ENABLED = {asset: True for asset in ASSETS}
LATEST_STATUS = {
    asset: {
        "status": "WAITING",
        "side": None,
        "score": None,
        "price": None,
        "stop": None,
        "t1": None,
        "t2": None,
        "t3": None,
        "reason": "Waiting for next closed 5M candle",
        "grade": "-",
        "rr": None,
        "daily_fibs": {},
        "four_hour_fibs": {},
        "five_min_fibs": {},
        "confluence": {},
        "option": None,
        "updated_at": None,
    }
    for asset in ASSETS
}


# ============================================================
# RENDER FREE WEB SERVICE / HEALTH SERVER
# ============================================================

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b"KRYPT BRO Signal Engine: RUNNING"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Avoid filling Render logs with health-check requests.
        return


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    try:
        with ReusableTCPServer(("0.0.0.0", port), HealthHandler) as server:
            logger.info("Health server listening on port %s", port)
            server.serve_forever()
    except Exception:
        logger.exception("Health server failed")


def keep_alive_ping():
    """
    Optional ping loop.

    Set RENDER_EXTERNAL_URL in Render if available, e.g.
    https://your-service.onrender.com

    Note: a self-ping is only a best-effort health request. Hosting-platform
    sleep/idle policy is controlled by the platform and cannot be guaranteed
    away by application code.
    """
    time.sleep(30)
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

    if not render_url:
        logger.info("RENDER_EXTERNAL_URL not set; self-ping disabled")
        return

    health_url = f"{render_url}/health"
    logger.info("Keep-alive health ping enabled")

    while True:
        try:
            response = requests.get(health_url, timeout=10)
            logger.debug("Health ping status: %s", response.status_code)
        except Exception as exc:
            logger.warning("Health ping failed: %s", exc)

        time.sleep(600)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(message: str) -> None:
    if not TELEGRAM_ENABLED:
        logger.info("Telegram delivery is OFF.")
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured.\n%s", message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if not response.ok:
            logger.error("Telegram error %s: %s", response.status_code, response.text)
    except Exception:
        logger.exception("Telegram send failed")


# ============================================================
# MARKET DATA
# ============================================================

def fetch_candles(asset: str, interval: str, count: int = 200) -> pd.DataFrame:
    """
    Fetch OHLCV candles directly from Delta Exchange India.

    Public endpoint:
      GET /v2/history/candles

    No Delta dependency and no API key required for this market-data call.
    """
    symbol = DELTA_SYMBOLS.get(asset)
    seconds = INTERVAL_SECONDS.get(interval)

    if not symbol or not seconds:
        logger.error("Unsupported Delta symbol/interval: %s %s", asset, interval)
        return pd.DataFrame()

    # Request enough history for the desired number of candles.
    # Add a small cushion because the newest candle can be forming.
    end_ts = int(time.time())
    start_ts = end_ts - (seconds * (count + 5))

    url = f"{DELTA_BASE_URL}/v2/history/candles"
    params = {
        "resolution": interval,
        "symbol": symbol,
        "start": start_ts,
        "end": end_ts,
    }
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=12)

        if response.status_code != 200:
            logger.error(
                "Delta candle HTTP error %s | %s %s | %s",
                response.status_code,
                asset,
                interval,
                response.text[:300],
            )
            return pd.DataFrame()

        payload = response.json()

        if not payload.get("success"):
            logger.error(
                "Delta candle API rejected %s %s: %s",
                asset,
                interval,
                payload,
            )
            return pd.DataFrame()

        rows = payload.get("result", [])
        if not rows:
            logger.warning("No Delta candles returned for %s %s", asset, interval)
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        required = {"time", "open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            logger.error(
                "Unexpected Delta candle response for %s %s. Columns=%s",
                asset,
                interval,
                list(df.columns),
            )
            return pd.DataFrame()

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        df = df.dropna(subset=["time", "open", "high", "low", "close", "volume"])

        # Delta candle time is Unix seconds.
        df["open_time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df["close_time"] = pd.to_datetime(df["time"] + seconds, unit="s", utc=True)

        # Always work oldest -> newest, then keep only requested history.
        df = (
            df.sort_values("time")
            .drop_duplicates(subset=["time"], keep="last")
            .tail(count)
            .reset_index(drop=True)
        )

        return df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]

    except requests.RequestException as exc:
        logger.error("Delta network error for %s %s: %s", asset, interval, exc)
    except Exception:
        logger.exception("Failed to process Delta candles for %s %s", asset, interval)

    return pd.DataFrame()


# ============================================================
# INDICATORS
# ============================================================

def add_ema(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    out = df.copy()
    for period in periods:
        out[f"ema_{period}"] = out["close"].ewm(span=period, adjust=False).mean()
    return out


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    delta = out["close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, math.nan)
    out["rsi"] = 100 - (100 / (1 + rs))
    out["rsi"] = out["rsi"].fillna(50)
    return out


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    out["atr"] = tr.ewm(alpha=1 / period, adjust=False).mean()
    return out


def add_williams_r(df: pd.DataFrame, period: int = WILLIAMS_PERIOD) -> pd.DataFrame:
    """Williams %R, bounded roughly between -100 and 0."""
    out = df.copy()
    hh = out["high"].rolling(period, min_periods=period).max()
    ll = out["low"].rolling(period, min_periods=period).min()
    denom = (hh - ll).replace(0, math.nan)
    out["williams_r"] = -100.0 * (hh - out["close"]) / denom
    out["williams_r"] = out["williams_r"].fillna(-50.0).clip(-100.0, 0.0)
    return out


def add_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.DataFrame:
    """Wilder-style ADX with +DI/-DI for trend-strength confirmation."""
    out = df.copy()
    up = out["high"].diff()
    down = -out["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)

    prev_close = out["close"].shift(1)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - prev_close).abs(),
        (out["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean().replace(0, math.nan)
    plus_sm = plus_dm.ewm(alpha=1 / period, adjust=False).mean()
    minus_sm = minus_dm.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100.0 * plus_sm / atr
    minus_di = 100.0 * minus_sm / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, math.nan)

    out["plus_di"] = plus_di.fillna(0.0)
    out["minus_di"] = minus_di.fillna(0.0)
    out["adx"] = dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)
    return out


# ============================================================
# FIBONACCI PIVOTS
# ============================================================

FIB_MULTIPLIERS = {
    "1": 0.382,
    "2": 0.618,
    "3": 1.000,
    "4": 1.382,
    "5": 1.618,
}


def fibonacci_pivots(high: float, low: float, close: float) -> dict:
    """
    Extended Fibonacci pivot map:
      P = (H + L + C) / 3

      R1/R2/R3 = P + 0.382/0.618/1.000 * Range
      R4/R5    = P + 1.382/1.618 * Range
      S1..S5   = symmetric below Pivot

    R4/R5 are extensions used by this strategy; they are not universal
    exchange-standard pivot definitions.
    """
    pivot = (high + low + close) / 3.0
    price_range = high - low

    levels = {"P": pivot}

    for key, multiplier in FIB_MULTIPLIERS.items():
        levels[f"R{key}"] = pivot + multiplier * price_range
        levels[f"S{key}"] = pivot - multiplier * price_range

    return {k: round(v, 2) for k, v in levels.items()}


def get_daily_fib_levels(df_1d: pd.DataFrame) -> dict:
    if df_1d.empty:
        return {}

    now_utc = pd.Timestamp.now(tz="UTC")
    closed = df_1d[df_1d["close_time"] <= now_utc]
    if closed.empty:
        return {}

    candle = closed.iloc[-1]
    return fibonacci_pivots(
        float(candle["high"]),
        float(candle["low"]),
        float(candle["close"]),
    )


def get_5m_fib_levels(df_5m: pd.DataFrame) -> dict:
    if df_5m.empty:
        return {}

    now_utc = pd.Timestamp.now(tz="UTC")
    closed = df_5m[df_5m["close_time"] <= now_utc]
    if closed.empty:
        return {}

    candle = closed.iloc[-1]
    return fibonacci_pivots(
        float(candle["high"]),
        float(candle["low"]),
        float(candle["close"]),
    )


def get_4h_fib_levels(df_4h: pd.DataFrame) -> dict:
    if df_4h.empty:
        return {}
    now_utc = pd.Timestamp.now(tz="UTC")
    closed = df_4h[df_4h["close_time"] <= now_utc]
    if closed.empty:
        return {}
    candle = closed.iloc[-1]
    return fibonacci_pivots(float(candle["high"]), float(candle["low"]), float(candle["close"]))


def swing_fib_levels(df: pd.DataFrame, lookback: int = 48) -> dict:
    """Recent 15M range retracements. Used as soft confluence, never a hard gate."""
    if df.empty:
        return {}
    now_utc = pd.Timestamp.now(tz="UTC")
    closed = df[df["close_time"] <= now_utc].tail(lookback)
    if len(closed) < 12:
        return {}
    hi = float(closed["high"].max())
    lo = float(closed["low"].min())
    rng = hi - lo
    if rng <= 0:
        return {}
    return {
        "0.382": round(hi - 0.382 * rng, 2),
        "0.500": round(hi - 0.500 * rng, 2),
        "0.618": round(hi - 0.618 * rng, 2),
        "0.786": round(hi - 0.786 * rng, 2),
    }


def nearest_level(price: float, levels: dict) -> tuple[str | None, float | None, float]:
    best_name = None
    best_value = None
    best_distance = float("inf")

    for name, value in levels.items():
        distance = abs(price - value)
        if distance < best_distance:
            best_name = name
            best_value = value
            best_distance = distance

    return best_name, best_value, best_distance


def fib_confluence(price: float, daily: dict, five_min: dict) -> dict:
    """
    Finds:
      - nearest Daily Fib level to price
      - nearest 5M Fib level to price
      - whether both are close to current price
      - whether Daily and 5M levels are close to each other
    """
    d_name, d_value, d_dist = nearest_level(price, daily)
    m_name, m_value, m_dist = nearest_level(price, five_min)

    tolerance = price * (FIB_NEAR_PCT / 100.0)

    near_daily = d_value is not None and d_dist <= tolerance
    near_5m = m_value is not None and m_dist <= tolerance
    paired = (
        d_value is not None
        and m_value is not None
        and abs(d_value - m_value) <= tolerance
    )

    return {
        "daily_name": d_name,
        "daily_value": d_value,
        "five_name": m_name,
        "five_value": m_value,
        "near_daily": near_daily,
        "near_5m": near_5m,
        "paired": paired,
    }


# ============================================================
# MARKET STRUCTURE
# ============================================================

def recent_structure(df: pd.DataFrame, lookback: int = 8) -> str:
    """
    Simple structure filter using recent closed candles.
    Returns BULLISH / BEARISH / MIXED.
    """
    now_utc = pd.Timestamp.now(tz="UTC")
    closed = df[df["close_time"] <= now_utc].tail(lookback)
    if len(closed) < 4:
        return "MIXED"

    half = len(closed) // 2
    first = closed.iloc[:half]
    second = closed.iloc[half:]

    if (
        second["high"].max() > first["high"].max()
        and second["low"].min() > first["low"].min()
    ):
        return "BULLISH"

    if (
        second["high"].max() < first["high"].max()
        and second["low"].min() < first["low"].min()
    ):
        return "BEARISH"

    return "MIXED"


# ============================================================
# SIGNAL QUALITY GUARDS
# ============================================================

def candle_is_fresh(candle: pd.Series) -> bool:
    """Reject stale closed-candle data."""
    try:
        now = pd.Timestamp.now(tz="UTC")
        age = (now - candle["close_time"]).total_seconds()
        return 0 <= age <= MAX_SIGNAL_AGE_SECONDS
    except Exception:
        return False


def fib_context_for_side(side: str, price: float, daily: dict, four_hour: dict, five_min: dict, swing: dict | None = None) -> dict:
    """Direction-aware Daily/4H/5M pivot + swing-Fib context."""
    tolerance = price * (FIB_NEAR_PCT / 100.0)
    swing = swing or {}

    def candidates(levels, support):
        if support:
            return [(k, v) for k, v in levels.items() if (k.startswith("S") or k == "P") and v <= price + tolerance]
        return [(k, v) for k, v in levels.items() if (k.startswith("R") or k == "P") and v >= price - tolerance]

    support = side == "LONG"

    def nearest(items):
        if not items:
            return None, None
        return min(items, key=lambda item: abs(price - item[1]))

    d_name, d_value = nearest(candidates(daily, support))
    h4_name, h4_value = nearest(candidates(four_hour, support))
    m_name, m_value = nearest(candidates(five_min, support))
    sw_name, sw_value = nearest(list(swing.items()))

    directional_values = [v for v in (d_value, h4_value, m_value) if v is not None]
    pair_count = 0
    for i, a in enumerate(directional_values):
        for b in directional_values[i + 1:]:
            if abs(a - b) <= tolerance:
                pair_count += 1

    swing_near = sw_value is not None and abs(price - sw_value) <= tolerance
    paired = pair_count > 0
    triple = len(directional_values) == 3 and max(directional_values) - min(directional_values) <= tolerance

    return {
        "daily_name": d_name, "daily_value": d_value,
        "four_name": h4_name, "four_value": h4_value,
        "five_name": m_name, "five_value": m_value,
        "swing_name": sw_name if swing_near else None,
        "swing_value": sw_value if swing_near else None,
        "paired": paired,
        "triple": triple,
        "swing_near": swing_near,
    }


def reward_risk(entry: float, stop: float, target: float, side: str) -> float:
    if side == "LONG":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target
    if risk <= 0:
        return 0.0
    return reward / risk


# ============================================================
# LOW-LOAD 5M CANDLE GATE
# ============================================================

def get_latest_closed_5m(asset: str):
    """
    Lightweight gate:
    fetch only a few 5m candles and return the newest fully closed candle.
    The heavy multi-timeframe strategy runs only when this timestamp changes.
    """
    df = fetch_candles(asset, "5m", 4)
    if df.empty or len(df) < 2:
        return None

    now = pd.Timestamp.now(tz="UTC")
    closed = df[df["close_time"] <= now]

    if closed.empty:
        return None

    return closed.iloc[-1]


def has_new_closed_5m(asset: str) -> bool:
    candle = get_latest_closed_5m(asset)
    if candle is None:
        return False

    close_time = candle["close_time"]
    previous = LAST_PROCESSED_5M_CLOSE.get(asset)

    if previous is not None and close_time <= previous:
        return False

    # Mark it before running the heavy calculation so a transient error
    # doesn't create a high-frequency retry storm in the same candle.
    LAST_PROCESSED_5M_CLOSE[asset] = close_time
    logger.info(
        "%s new 5M candle closed at %s -> full strategy scan",
        asset,
        close_time,
    )
    return True



def append_signal_journal(record: dict) -> None:
    """Append one compact JSON line for later performance analysis."""
    try:
        with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")
    except Exception:
        logger.exception("Failed to write signal journal")


def breakout_retest_status(df_5m: pd.DataFrame, side: str, atr: float) -> dict:
    """
    Simple closed-candle breakout/retest confirmation.

    LONG:
      - recent close broke above prior local resistance
      - latest closed candle remains near/above that breakout level

    SHORT:
      - recent close broke below prior local support
      - latest closed candle remains near/below that breakout level
    """
    now_utc = pd.Timestamp.now(tz="UTC")
    closed = df_5m[df_5m["close_time"] <= now_utc].copy()
    need = max(BREAKOUT_LOOKBACK + 2, 8)
    if len(closed) < need:
        return {"confirmed": False, "level": None, "reason": "Not enough candles"}

    recent = closed.tail(need)
    latest = recent.iloc[-1]
    prev = recent.iloc[-2]
    base = recent.iloc[-(BREAKOUT_LOOKBACK + 2):-2]

    tolerance = max(atr * RETEST_TOLERANCE_ATR, 1e-9)

    if side == "LONG":
        level = float(base["high"].max())
        breakout = float(prev["close"]) > level
        retest = float(latest["low"]) <= level + tolerance and float(latest["close"]) >= level
        return {
            "confirmed": bool(breakout and retest),
            "level": round(level, 2),
            "reason": "Breakout + retest confirmed" if breakout and retest else "Waiting breakout/retest",
        }

    level = float(base["low"].min())
    breakout = float(prev["close"]) < level
    retest = float(latest["high"]) >= level - tolerance and float(latest["close"]) <= level
    return {
        "confirmed": bool(breakout and retest),
        "level": round(level, 2),
        "reason": "Breakdown + retest confirmed" if breakout and retest else "Waiting breakdown/retest",
    }


def pending_signal_gate(asset: str, side: str, setup: dict) -> dict:
    """Balanced retest gate with a strong-momentum fallback after a short wait."""
    current_close = setup.get("candle_close")
    pending = PENDING_SIGNALS.get(asset)

    if setup.get("retest_confirmed"):
        PENDING_SIGNALS[asset] = None
        return {"allowed": True, "state": "CONFIRMED", "fallback": False}

    strong_fallback = bool(setup.get("strong_fallback"))

    if pending is None or pending.get("side") != side:
        PENDING_SIGNALS[asset] = {"side": side, "first_close": current_close, "age": 1}
        return {"allowed": False, "state": "WAITING_RETEST", "fallback": False}

    pending["age"] += 1
    if strong_fallback and pending["age"] >= RETEST_BYPASS_AFTER_CANDLES:
        PENDING_SIGNALS[asset] = None
        return {"allowed": True, "state": "MOMENTUM_CONFIRM", "fallback": True}

    if pending["age"] > SIGNAL_EXPIRY_CANDLES:
        PENDING_SIGNALS[asset] = None
        return {"allowed": False, "state": "EXPIRED", "fallback": False}

    return {"allowed": False, "state": "WAITING_RETEST", "fallback": False}


# ============================================================
# DELTA OPTION PREMIUM / CONTRACT SELECTION (READ-ONLY)
# ============================================================

def _fnum(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _option_expiry_from_symbol(symbol: str, asset: str) -> datetime | None:
    """Parse C-BTC-90000-310125 style symbols into an aware expiry datetime."""
    try:
        date_token = str(symbol).split("-")[-1]
        expiry_day = datetime.strptime(date_token, "%d%m%y")
        hour, minute = (21, 30) if asset == "GOLD" else (17, 30)
        ist = ZoneInfo("Asia/Kolkata")
        return expiry_day.replace(hour=hour, minute=minute, tzinfo=ist)
    except Exception:
        return None


def fetch_delta_option_chain(asset: str) -> list[dict]:
    """Best-effort public Delta option-chain fetch. Failure never blocks core signals."""
    rows = []
    for underlying in OPTION_UNDERLYINGS.get(asset, [asset]):
        try:
            response = requests.get(
                f"{DELTA_BASE_URL}/v2/tickers",
                params={
                    "contract_types": "call_options,put_options",
                    "underlying_asset_symbols": underlying,
                },
                headers={"Accept": "application/json"},
                timeout=OPTION_CHAIN_TIMEOUT,
            )
            if not response.ok:
                continue
            payload = response.json()
            result = payload.get("result", []) if isinstance(payload, dict) else []
            if result:
                rows = [r for r in result if isinstance(r, dict)]
                if rows:
                    break
        except Exception as exc:
            logger.debug("%s option chain fetch failed for %s: %s", asset, underlying, exc)
    return rows



def build_option_chain_snapshot(asset: str, underlying_price: float, chain: list[dict] | None = None, wing_count: int = 4) -> dict | None:
    """Return nearest-expiry option premiums around spot: ATM + N strikes above/below.

    Read-only helper. Uses ask price when available (realistic option-buy price),
    otherwise mark price. Failure is non-fatal and never affects the signal engine.
    """
    if chain is None:
        chain = fetch_delta_option_chain(asset)
    if not chain:
        return None

    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    parsed = []
    for row in chain:
        ctype = row.get("contract_type")
        if ctype not in ("call_options", "put_options"):
            continue
        symbol = str(row.get("symbol") or "")
        expiry = _option_expiry_from_symbol(symbol, asset)
        strike = _fnum(row.get("strike_price"))
        mark = _fnum(row.get("mark_price"))
        if expiry is None or strike is None or mark is None or mark <= 0:
            continue
        hours_left = (expiry - now_ist).total_seconds() / 3600.0
        if hours_left < OPTION_MIN_EXPIRY_HOURS:
            continue
        quotes = row.get("quotes") or {}
        bid = _fnum(quotes.get("best_bid"))
        ask = _fnum(quotes.get("best_ask"))
        premium = ask if ask is not None and ask > 0 else mark
        parsed.append({
            "contract_type": ctype,
            "symbol": symbol,
            "expiry": expiry,
            "strike": strike,
            "mark": mark,
            "bid": bid,
            "ask": ask,
            "premium": premium,
        })

    if not parsed:
        return None

    nearest_expiry = min(x["expiry"] for x in parsed)
    rows = [x for x in parsed if x["expiry"] == nearest_expiry]
    strikes = sorted({x["strike"] for x in rows})
    if not strikes:
        return None

    atm_index = min(range(len(strikes)), key=lambda i: abs(strikes[i] - underlying_price))
    lo = max(0, atm_index - max(1, int(wing_count)))
    hi = min(len(strikes), atm_index + max(1, int(wing_count)) + 1)
    selected_strikes = strikes[lo:hi]

    by_key = {(x["strike"], x["contract_type"]): x for x in rows}
    ladder = []
    for strike in selected_strikes:
        call = by_key.get((strike, "call_options"))
        put = by_key.get((strike, "put_options"))
        ladder.append({
            "strike": round(strike, 8),
            "is_atm": strike == strikes[atm_index],
            "call_premium": round(call["premium"], 4) if call else None,
            "put_premium": round(put["premium"], 4) if put else None,
            "call_mark": round(call["mark"], 4) if call else None,
            "put_mark": round(put["mark"], 4) if put else None,
            "call_symbol": call["symbol"] if call else None,
            "put_symbol": put["symbol"] if put else None,
        })

    return {
        "spot": round(float(underlying_price), 4),
        "atm_strike": round(strikes[atm_index], 8),
        "expiry": nearest_expiry.strftime("%d-%m-%Y %H:%M IST"),
        "wing_count": int(wing_count),
        "rows": ladder,
        "premium_source": "best ask when available, otherwise mark",
    }


def select_option_contract(asset: str, side: str, underlying_price: float, underlying_stop: float, targets: list[float], chain: list[dict] | None = None) -> dict | None:
    """
    Choose a liquid near-ATM/near-ITM Delta option and calculate current premium
    plus Greek-based premium estimates at underlying SL/T1/T2/T3.

    These are estimates only; IV/theta changes can materially alter realised premium.
    """
    if chain is None:
        chain = fetch_delta_option_chain(asset)
    if not chain:
        return None

    want_type = "call_options" if side == "LONG" else "put_options"
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    candidates = []

    for row in chain:
        if row.get("contract_type") != want_type:
            continue
        symbol = str(row.get("symbol") or "")
        expiry = _option_expiry_from_symbol(symbol, asset)
        if expiry is None:
            continue
        hours_left = (expiry - now_ist).total_seconds() / 3600.0
        if hours_left < OPTION_MIN_EXPIRY_HOURS:
            continue

        strike = _fnum(row.get("strike_price"))
        mark = _fnum(row.get("mark_price"))
        quotes = row.get("quotes") or {}
        bid = _fnum(quotes.get("best_bid"))
        ask = _fnum(quotes.get("best_ask"))
        oi = _fnum(row.get("oi"), 0.0) or 0.0
        volume = _fnum(row.get("volume"), 0.0) or 0.0
        greeks = row.get("greeks") or {}
        delta = _fnum(greeks.get("delta"))
        gamma = _fnum(greeks.get("gamma"), 0.0) or 0.0
        theta = _fnum(greeks.get("theta"))
        iv = _fnum(row.get("mark_vol"))

        if strike is None or mark is None or mark <= 0:
            continue
        mid = None
        spread_pct = None
        if bid is not None and ask is not None and bid > 0 and ask >= bid:
            mid = (bid + ask) / 2.0
            spread_pct = ((ask - bid) / max(mid, 1e-9)) * 100.0
            if spread_pct > OPTION_MAX_SPREAD_PCT:
                continue

        entry_premium = ask if ask is not None and ask > 0 else (mid if mid else mark)
        abs_delta = abs(delta) if delta is not None else None
        if abs_delta is not None and not (OPTION_TARGET_DELTA_MIN <= abs_delta <= OPTION_TARGET_DELTA_MAX):
            continue

        # Prefer same nearest expiry first, then near-ATM with slight ITM preference,
        # tighter spread, greater OI and volume.
        moneyness = abs(strike - underlying_price) / max(underlying_price, 1e-9)
        itm = (side == "LONG" and strike <= underlying_price) or (side == "SHORT" and strike >= underlying_price)
        score = 100.0
        score -= moneyness * 1000.0
        score += 3.0 if itm else 0.0
        score -= (spread_pct or 6.0) * 0.8
        score += min(math.log10(oi + 1.0) * 2.0, 10.0)
        score += min(math.log10(volume + 1.0), 5.0)

        candidates.append({
            "row": row, "symbol": symbol, "expiry": expiry, "hours_left": hours_left,
            "strike": strike, "mark": mark, "entry": entry_premium, "bid": bid, "ask": ask,
            "spread_pct": spread_pct, "oi": oi, "volume": volume, "delta": delta,
            "gamma": gamma, "theta": theta, "iv": iv, "liquidity_score": score,
        })

    if not candidates:
        return None

    nearest_expiry = min(c["expiry"] for c in candidates)
    same_expiry = [c for c in candidates if c["expiry"] == nearest_expiry]
    chosen = max(same_expiry, key=lambda c: c["liquidity_score"])

    def premium_estimate(underlying_target):
        # Delta/Gamma approximation around current spot. Keep estimates non-negative.
        if chosen["delta"] is None:
            return None
        ds = float(underlying_target) - underlying_price
        est = chosen["mark"] + chosen["delta"] * ds + 0.5 * chosen["gamma"] * (ds ** 2)
        return round(max(est, 0.01), 2)

    return {
        "symbol": chosen["symbol"],
        "contract_type": "CALL" if side == "LONG" else "PUT",
        "strike": round(chosen["strike"], 2),
        "expiry": chosen["expiry"].strftime("%d-%m-%Y %H:%M IST"),
        "hours_to_expiry": round(chosen["hours_left"], 1),
        "premium_entry": round(chosen["entry"], 2),
        "mark_price": round(chosen["mark"], 2),
        "best_bid": round(chosen["bid"], 2) if chosen["bid"] is not None else None,
        "best_ask": round(chosen["ask"], 2) if chosen["ask"] is not None else None,
        "spread_pct": round(chosen["spread_pct"], 2) if chosen["spread_pct"] is not None else None,
        "oi": round(chosen["oi"], 2),
        "volume": round(chosen["volume"], 2),
        "delta": round(chosen["delta"], 4) if chosen["delta"] is not None else None,
        "gamma": round(chosen["gamma"], 8),
        "theta": round(chosen["theta"], 4) if chosen["theta"] is not None else None,
        "iv": round(chosen["iv"], 4) if chosen["iv"] is not None else None,
        "premium_sl_est": premium_estimate(underlying_stop),
        "premium_t1_est": premium_estimate(targets[0]),
        "premium_t2_est": premium_estimate(targets[1]),
        "premium_t3_est": premium_estimate(targets[2]),
        "estimate_note": "Greek estimate; actual premium changes with IV, theta and order-book movement.",
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(asset: str) -> dict | None:
    # Existing runtime/scanner architecture is intentionally unchanged.
    # Only strategy inputs/scoring are enriched here.
    df_1d = fetch_candles(asset, "1d", 10)
    df_4h = fetch_candles(asset, "4h", 100)
    df_1h = fetch_candles(asset, "1h", 120)
    df_15m = fetch_candles(asset, "15m", 150)
    df_5m = fetch_candles(asset, "5m", 200)

    if any(df.empty for df in [df_1d, df_4h, df_1h, df_15m, df_5m]):
        return None

    df_4h = add_adx(add_ema(df_4h, [20, 50]), ADX_PERIOD)
    df_1h = add_adx(add_ema(df_1h, [20, 50]), ADX_PERIOD)
    df_15m = add_williams_r(add_adx(add_rsi(add_ema(df_15m, [9, 21]), 14), ADX_PERIOD), WILLIAMS_PERIOD)
    df_5m = add_williams_r(add_adx(add_atr(add_rsi(add_ema(df_5m, [9, 21]), 14), 14), ADX_PERIOD), WILLIAMS_PERIOD)

    now_utc = pd.Timestamp.now(tz="UTC")
    h4_closed = df_4h[df_4h["close_time"] <= now_utc]
    h1_closed = df_1h[df_1h["close_time"] <= now_utc]
    m15_closed = df_15m[df_15m["close_time"] <= now_utc]
    m5_closed = df_5m[df_5m["close_time"] <= now_utc]
    if h4_closed.empty or h1_closed.empty or m15_closed.empty or m5_closed.empty:
        return None

    h4, h1, m15, m5 = h4_closed.iloc[-1], h1_closed.iloc[-1], m15_closed.iloc[-1], m5_closed.iloc[-1]
    current_price = float(m5["close"])

    if not candle_is_fresh(m5):
        logger.warning("%s: stale 5M candle; signal skipped", asset)
        return None

    daily_fibs = get_daily_fib_levels(df_1d)
    four_hour_fibs = get_4h_fib_levels(df_4h)
    five_min_fibs = get_5m_fib_levels(df_5m)
    swing_fibs = swing_fib_levels(df_15m)
    if not daily_fibs or not four_hour_fibs or not five_min_fibs:
        return None

    structure = recent_structure(df_5m, 8)

    # ---------- Direction ----------
    h4_bull = h4["ema_20"] > h4["ema_50"] and h4["close"] > h4["ema_20"]
    h4_bear = h4["ema_20"] < h4["ema_50"] and h4["close"] < h4["ema_20"]
    h1_bull = h1["ema_20"] > h1["ema_50"] and h1["close"] > h1["ema_20"]
    h1_bear = h1["ema_20"] < h1["ema_50"] and h1["close"] < h1["ema_20"]
    m15_bull = m15["ema_9"] > m15["ema_21"] and m15["rsi"] >= 52
    m15_bear = m15["ema_9"] < m15["ema_21"] and m15["rsi"] <= 48
    m5_bull = m5["ema_9"] > m5["ema_21"] and m5["close"] > m5["ema_9"]
    m5_bear = m5["ema_9"] < m5["ema_21"] and m5["close"] < m5["ema_9"]

    # ---------- Volume ----------
    closed_5m = m5_closed
    vol_avg_20 = float(closed_5m["volume"].tail(20).mean())
    volume_ok = float(m5["volume"]) >= vol_avg_20 * VOLUME_MULTIPLIER
    candle_direction_long = float(m5["close"]) >= float(m5["open"])
    candle_direction_short = float(m5["close"]) <= float(m5["open"])

    # ---------- Williams %R / ADX ----------
    wr15 = float(m15["williams_r"])
    wr5 = float(m5["williams_r"])
    prev_wr5 = float(m5_closed.iloc[-2]["williams_r"]) if len(m5_closed) >= 2 else wr5
    will_long = (prev_wr5 <= -80 and wr5 > prev_wr5) or (-80 <= wr15 <= -35 and wr5 > -70)
    will_short = (prev_wr5 >= -20 and wr5 < prev_wr5) or (-65 <= wr15 <= -20 and wr5 < -30)

    adx15 = float(m15["adx"]); plus15 = float(m15["plus_di"]); minus15 = float(m15["minus_di"])
    adx_long = adx15 >= ADX_TREND_MIN and plus15 > minus15
    adx_short = adx15 >= ADX_TREND_MIN and minus15 > plus15

    # ---------- Directional Fib context ----------
    long_fib = fib_context_for_side("LONG", current_price, daily_fibs, four_hour_fibs, five_min_fibs, swing_fibs)
    short_fib = fib_context_for_side("SHORT", current_price, daily_fibs, four_hour_fibs, five_min_fibs, swing_fibs)

    # ---------- Base score: preserve proven original weighting ----------
    long_score = 0
    short_score = 0
    if h1_bull: long_score += 20
    if h1_bear: short_score += 20
    if m15_bull: long_score += 15
    if m15_bear: short_score += 15
    if m5_bull: long_score += 20
    if m5_bear: short_score += 20
    if volume_ok and candle_direction_long: long_score += 15
    if volume_ok and candle_direction_short: short_score += 15
    if 55 <= m15["rsi"] <= 72: long_score += 10
    if 28 <= m15["rsi"] <= 45: short_score += 10
    if structure == "BULLISH": long_score += 10
    elif structure == "BEARISH": short_score += 10

    # Original neutral Fib points are replaced by direction-aware Fib points.
    def fib_points(ctx):
        if ctx.get("triple"): return 10
        if ctx.get("paired") and ctx.get("swing_near"): return 10
        if ctx.get("paired"): return 8
        if ctx.get("swing_near"): return 4
        if any(ctx.get(k) is not None for k in ("daily_name", "four_name", "five_name")): return 3
        return 0
    long_score += fib_points(long_fib)
    short_score += fib_points(short_fib)

    # ---------- Soft confirmation polish ----------
    # 4H trend is intentionally NOT a hard gate: it upgrades alignment and
    # penalises counter-trend setups without blocking valid reversals.
    if h4_bull: long_score += 8
    if h4_bear: short_score += 8
    if h4_bear: long_score -= 8
    if h4_bull: short_score -= 8

    if adx_long: long_score += 6
    elif adx15 < ADX_TREND_MIN: long_score -= 3
    if adx_short: short_score += 6
    elif adx15 < ADX_TREND_MIN: short_score -= 3

    if will_long: long_score += 5
    if will_short: short_score += 5

    # A disagreement with the already-established 1H trend is allowed but must
    # earn enough confirmation elsewhere; this addresses the weak 1H-crossed
    # screenshot examples without changing the scanner architecture.
    if h1_bear: long_score -= 7
    if h1_bull: short_score -= 7

    long_score = max(0, min(100, int(round(long_score))))
    short_score = max(0, min(100, int(round(short_score))))

    # ---------- TRUE SCALP sideways/volatility/extension guard v2.5 ----------
    ema_gap_pct = abs(m5["ema_9"] - m5["ema_21"]) / current_price * 100
    atr_pct = float(m5["atr"]) / current_price * 100
    choppy = ema_gap_pct < 0.03 and atr_pct < MIN_ATR_PCT
    extreme_low_vol = atr_pct < (MIN_ATR_PCT * 0.45)
    extreme_high_vol = atr_pct > MAX_ATR_PCT
    ema_extension_atr = abs(current_price - float(m5["ema_9"])) / max(float(m5["atr"]), 1e-9)
    overextended = ema_extension_atr > MAX_EMA_EXTENSION_ATR
    extreme_extension = ema_extension_atr > EXTREME_EXTENSION_ATR

    if choppy:
        long_score = max(0, long_score - CHOPPY_PENALTY)
        short_score = max(0, short_score - CHOPPY_PENALTY)
    if overextended:
        long_score = max(0, long_score - OVEREXTENDED_PENALTY)
        short_score = max(0, short_score - OVEREXTENDED_PENALTY)

    common = {
        "asset": asset, "price": current_price, "long_score": long_score, "short_score": short_score,
        "daily_fibs": daily_fibs, "four_hour_fibs": four_hour_fibs, "five_min_fibs": five_min_fibs,
    }
    if extreme_low_vol or extreme_high_vol or extreme_extension:
        return {**common, "status": "NO_TRADE", "reason": "Extreme volatility / extension guard", "confluence": long_fib if long_score >= short_score else short_fib}

    threshold = effective_signal_threshold()
    if long_score >= threshold and long_score > short_score:
        side, score, side_fib = "LONG", long_score, long_fib
    elif short_score >= threshold and short_score > long_score:
        side, score, side_fib = "SHORT", short_score, short_fib
    else:
        return {**common, "status": "NO_TRADE", "reason": f"Score below threshold ({threshold})", "confluence": long_fib if long_score >= short_score else short_fib}

    trigger_ok = m5_bull if side == "LONG" else m5_bear
    if REQUIRE_5M_TRIGGER and not trigger_ok:
        return {**common, "status": "NO_TRADE", "reason": "5M trigger missing", "confluence": side_fib}

    # Volume is a soft confirmation in v2.4.
    if REQUIRE_VOLUME_FOR_SIGNAL and not volume_ok:
        score = max(0, score - VOLUME_MISSING_PENALTY)
        if side == "LONG":
            long_score = score
        else:
            short_score = score
        common["long_score"], common["short_score"] = long_score, short_score
        if score < threshold:
            return {**common, "status": "NO_TRADE", "reason": f"Volume soft penalty -> score below threshold ({threshold})", "confluence": side_fib}

    if side_fib["daily_name"] is None and side_fib["four_name"] is None and side_fib["five_name"] is None:
        return {**common, "status": "NO_TRADE", "reason": "No direction-aware Fib context", "confluence": side_fib}

    trend_aligned = (h4_bull and h1_bull) if side == "LONG" else (h4_bear and h1_bear)
    setup_aligned = m15_bull if side == "LONG" else m15_bear
    adx_aligned = adx_long if side == "LONG" else adx_short
    structure_aligned = structure == ("BULLISH" if side == "LONG" else "BEARISH")
    strong_fallback = (score >= RETEST_BYPASS_SCORE and trigger_ok and trend_aligned and (setup_aligned or adx_aligned or structure_aligned))

    atr_now = float(m5["atr"])
    retest_info = breakout_retest_status(df_5m, side, atr_now)
    gate = pending_signal_gate(asset, side, {
        "retest_confirmed": retest_info["confirmed"],
        "strong_fallback": strong_fallback,
        "candle_close": str(m5["close_time"]),
    })
    if not gate["allowed"]:
        return {**common, "status": "NO_TRADE", "reason": f"{gate['state']}: {retest_info['reason']}", "confluence": side_fib}

    atr = float(m5["atr"])
    swing_low = float(closed_5m["low"].tail(6).min())
    swing_high = float(closed_5m["high"].tail(6).max())
    if side == "LONG":
        stop = min(swing_low, current_price - ATR_SL_MULTIPLIER * atr)
        risk = current_price - stop
        if risk <= 0: return None
        t1, t2, t3 = current_price + risk, current_price + MIN_RR * risk, current_price + 2.5 * risk
    else:
        stop = max(swing_high, current_price + ATR_SL_MULTIPLIER * atr)
        risk = stop - current_price
        if risk <= 0: return None
        t1, t2, t3 = current_price - risk, current_price - MIN_RR * risk, current_price - 2.5 * risk

    rr_t2 = reward_risk(current_price, stop, t2, side)
    if rr_t2 + 1e-9 < MIN_RR:
        return {**common, "status": "NO_TRADE", "reason": f"R:R below minimum ({rr_t2:.2f})", "confluence": side_fib}

    # Option-chain lookup happens only after the underlying setup is fully
    # confirmed. API failure is non-fatal and cannot stop the scanner.
    option = None
    option_chain = None
    try:
        # One public API fetch is reused for both the compact chain display and
        # the directional option selection. This keeps the existing scanner light.
        raw_option_chain = fetch_delta_option_chain(asset)
        option_chain = build_option_chain_snapshot(asset, current_price, raw_option_chain, wing_count=4)
        option = select_option_contract(asset, side, current_price, stop, [t1, t2, t3], chain=raw_option_chain)
    except Exception:
        logger.exception("%s option premium enrichment failed", asset)

    return {
        **common,
        "status": "SIGNAL", "side": side, "score": score,
        "price": round(current_price, 2), "stop": round(stop, 2),
        "t1": round(t1, 2), "t2": round(t2, 2), "t3": round(t3, 2),
        "rsi_15m": round(float(m15["rsi"]), 1), "williams_15m": round(wr15, 1),
        "williams_5m": round(wr5, 1), "adx_15m": round(adx15, 1),
        "plus_di_15m": round(plus15, 1), "minus_di_15m": round(minus15, 1),
        "volume_ok": volume_ok, "structure": structure, "confluence": side_fib,
        "rr_t2": round(rr_t2, 2), "retest_confirmed": bool(retest_info.get("confirmed")),
        "retest_mode": gate.get("state"), "retest_level": retest_info.get("level"),
        "signal_threshold": threshold,
        "h4_bull": h4_bull, "h4_bear": h4_bear, "h1_bull": h1_bull, "h1_bear": h1_bear,
        "m15_bull": m15_bull, "m15_bear": m15_bear, "m5_bull": m5_bull, "m5_bear": m5_bear,
        "adx_long": adx_long, "adx_short": adx_short, "will_long": will_long, "will_short": will_short,
        "option": option,
        "option_chain": option_chain,
    }


def signal_grade(score: int | float | None) -> str:
    if score is None:
        return "-"
    if score >= 90:
        return "A+"
    if score >= 82:
        return "A"
    if score >= MIN_SIGNAL_SCORE:
        return "B"
    return "NO TRADE"


# ============================================================
# MESSAGE FORMAT
# ============================================================

def format_signal(signal: dict) -> str:
    asset = signal["asset"]
    if signal["status"] != "SIGNAL":
        return (
            f"⛔ <b>KRYPT BRO - NO TRADE</b>\n\n"
            f"<b>{asset}</b> @ ${signal['price']:,.2f}\n"
            f"Reason: {signal['reason']}\n"
            f"Long Score: {signal['long_score']}/100\n"
            f"Short Score: {signal['short_score']}/100"
        )

    side = signal["side"]
    side_icon = "🟢" if side == "LONG" else "🔴"
    c = signal["confluence"]
    quality = "STRONG" if signal["score"] >= 85 else "GOOD"

    def level_text(name_key, value_key):
        n, v = c.get(name_key), c.get(value_key)
        return f"{n} ${v:,.2f}" if n and v is not None else "N/A"

    daily_text = level_text("daily_name", "daily_value")
    four_text = level_text("four_name", "four_value")
    five_text = level_text("five_name", "five_value")
    swing_text = level_text("swing_name", "swing_value")

    text = (
        f"🔥 <b>KRYPT BRO SIGNAL</b>\n\n"
        f"{side_icon} <b>{asset} {side}</b>\n"
        f"Quality: <b>{quality}</b>\n"
        f"Score: <b>{signal['score']}/100</b>\n"
        f"Gate: <b>{signal.get('retest_mode', 'CONFIRMED')}</b>\n\n"
        f"Entry: <b>${signal['price']:,.2f}</b>\n"
        f"SL: <b>${signal['stop']:,.2f}</b>\n"
        f"T1: <b>${signal['t1']:,.2f}</b>\n"
        f"T2: <b>${signal['t2']:,.2f}</b>\n"
        f"T3: <b>${signal['t3']:,.2f}</b>\n"
        f"R:R to T2: <b>1:{signal['rr_t2']:.2f}</b>\n\n"
        f"4H Trend: {'✅' if (signal['h4_bull'] if side == 'LONG' else signal['h4_bear']) else '⚠️'}\n"
        f"1H Trend: {'✅' if (signal['h1_bull'] if side == 'LONG' else signal['h1_bear']) else '⚠️'}\n"
        f"15M Setup: {'✅' if (signal['m15_bull'] if side == 'LONG' else signal['m15_bear']) else '❌'}\n"
        f"5M Trigger: {'✅' if (signal['m5_bull'] if side == 'LONG' else signal['m5_bear']) else '❌'}\n"
        f"Volume: {'✅' if signal['volume_ok'] else '❌'}\n"
        f"Structure: <b>{signal['structure']}</b>\n"
        f"15M RSI: <b>{signal['rsi_15m']}</b>\n"
        f"Williams %R 15M/5M: <b>{signal['williams_15m']} / {signal['williams_5m']}</b>\n"
        f"ADX 15M: <b>{signal['adx_15m']}</b> (+DI {signal['plus_di_15m']} / -DI {signal['minus_di_15m']})\n\n"
        f"Daily Fib Near: <b>{daily_text}</b>\n"
        f"4H Fib Near: <b>{four_text}</b>\n"
        f"5M Fib Near: <b>{five_text}</b>\n"
        f"Swing Fib Near: <b>{swing_text}</b>\n"
        f"Fib Confluence: <b>{'🔥 TRIPLE' if c.get('triple') else ('✅ YES' if c.get('paired') else 'NO')}</b>"
    )

    chain_view = signal.get("option_chain")
    if chain_view and chain_view.get("rows"):
        def _premium_text(value):
            if value is None:
                return "-"
            v = float(value)
            if abs(v) >= 1000:
                return f"{v:,.0f}"
            if abs(v) >= 100:
                return f"{v:,.1f}"
            if abs(v) >= 1:
                return f"{v:,.2f}"
            return f"{v:,.4f}"

        text += (
            f"\n\n📊 <b>DELTA OPTION CHAIN · NEAREST EXPIRY</b>\n"
            f"Spot: <b>${chain_view['spot']:,.2f}</b> | ATM: <b>{chain_view['atm_strike']:,.2f}</b>\n"
            f"Expiry: <b>{chain_view['expiry']}</b>\n"
            f"<code>CALL        STRIKE        PUT</code>\n"
        )
        for row in chain_view["rows"]:
            atm = " ◀ATM" if row.get("is_atm") else ""
            cp = _premium_text(row.get("call_premium"))
            pp = _premium_text(row.get("put_premium"))
            strike = f"{float(row['strike']):,.2f}"
            text += f"<code>{cp:>8}  {strike:>12}  {pp:>8}</code>{atm}\n"
        text += "<i>Premium = best ask when available; otherwise mark.</i>"
    else:
        text += "\n\n📊 <b>DELTA OPTION CHAIN</b>\nPremium ladder unavailable; core signal continues normally."

    opt = signal.get("option")
    if opt:
        spread = f"{opt['spread_pct']:.1f}%" if opt.get("spread_pct") is not None else "N/A"
        delta = f"{opt['delta']:.3f}" if opt.get("delta") is not None else "N/A"
        psl = f"${opt['premium_sl_est']:,.2f}" if opt.get("premium_sl_est") is not None else "N/A"
        pt1 = f"${opt['premium_t1_est']:,.2f}" if opt.get("premium_t1_est") is not None else "N/A"
        pt2 = f"${opt['premium_t2_est']:,.2f}" if opt.get("premium_t2_est") is not None else "N/A"
        pt3 = f"${opt['premium_t3_est']:,.2f}" if opt.get("premium_t3_est") is not None else "N/A"
        text += (
            f"\n\n🎯 <b>DELTA OPTION</b>\n"
            f"{opt['symbol']} | {opt['contract_type']}\n"
            f"Strike: <b>${opt['strike']:,.2f}</b> | Exp: <b>{opt['expiry']}</b>\n"
            f"Premium now: <b>${opt['premium_entry']:,.2f}</b> (mark ${opt['mark_price']:,.2f})\n"
            f"Premium est SL/T1/T2/T3: <b>{psl} / {pt1} / {pt2} / {pt3}</b>\n"
            f"Delta: <b>{delta}</b> | OI: <b>{opt['oi']:,.0f}</b> | Vol: <b>{opt['volume']:,.0f}</b> | Spread: <b>{spread}</b>\n"
            f"<i>Premium targets are Greek estimates, not guaranteed fills.</i>"
        )
    else:
        text += "\n\n🎯 <b>DELTA OPTION</b>\nOption-chain premium unavailable; underlying signal remains valid."
    return text


# ============================================================
# SCANNER
# ============================================================

def should_send_signal(asset: str, side: str) -> bool:
    # Lifecycle V3.1: while an asset has an unresolved active signal,
    # never send a second entry signal for that asset.
    active_map = globals().get("ACTIVE_SIGNALS", {})
    active = active_map.get(asset) if isinstance(active_map, dict) else None
    if active:
        logger.info(
            "%s %s Telegram entry blocked: lifecycle signal still %s",
            asset, side, active.get("status", "ACTIVE")
        )
        return False

    now = time.time()
    previous = LAST_SIGNAL[asset]

    same_side = previous["side"] == side
    still_in_cooldown = (now - previous["time"]) < SIGNAL_COOLDOWN_SECONDS

    if same_side and still_in_cooldown:
        return False

    LAST_SIGNAL[asset] = {"side": side, "time": now}
    return True


def scan_once() -> None:
    if not SCANNER_ENABLED:
        logger.info("Signal scanner is STOPPED")
        return

    for asset in ASSETS:
        try:
            if not ASSET_ENABLED.get(asset, True):
                continue

            # Lightweight 5M gate first. Full MTF calculation occurs
            # only once per newly closed 5-minute candle.
            if not has_new_closed_5m(asset):
                continue

            signal = calculate_signal(asset)
            if not signal:
                continue

            # Save latest result for the web dashboard.
            now_txt = datetime.now(timezone.utc).isoformat()
            if signal["status"] == "SIGNAL":
                LATEST_STATUS[asset] = {
                    "status": "SIGNAL",
                    "side": signal.get("side"),
                    "score": signal.get("score"),
                    "price": signal.get("price"),
                    "stop": signal.get("stop"),
                    "t1": signal.get("t1"),
                    "t2": signal.get("t2"),
                    "t3": signal.get("t3"),
                    "reason": None,
                    "grade": signal_grade(signal.get("score")),
                    "rr": signal.get("rr_t2"),
                    "daily_fibs": signal.get("daily_fibs", {}),
                    "four_hour_fibs": signal.get("four_hour_fibs", {}),
                    "five_min_fibs": signal.get("five_min_fibs", {}),
                    "confluence": signal.get("confluence", {}),
                    "option": signal.get("option"),
                    "updated_at": now_txt,
                }
            else:
                LATEST_STATUS[asset] = {
                    "status": "NO_TRADE",
                    "side": None,
                    "score": max(signal.get("long_score", 0), signal.get("short_score", 0)),
                    "price": signal.get("price"),
                    "stop": None,
                    "t1": None,
                    "t2": None,
                    "t3": None,
                    "reason": signal.get("reason"),
                    "grade": signal_grade(max(signal.get("long_score", 0), signal.get("short_score", 0))),
                    "rr": None,
                    "daily_fibs": signal.get("daily_fibs", {}),
                    "four_hour_fibs": signal.get("four_hour_fibs", {}),
                    "five_min_fibs": signal.get("five_min_fibs", {}),
                    "confluence": signal.get("confluence", {}),
                    "option": signal.get("option"),
                    "updated_at": now_txt,
                }

            if signal["status"] == "SIGNAL":
                append_signal_journal({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "asset": asset,
                    "side": signal.get("side"),
                    "grade": signal_grade(signal.get("score")) if "signal_grade" in globals() else None,
                    "score": signal.get("score"),
                    "entry": signal.get("price"),
                    "sl": signal.get("stop"),
                    "t1": signal.get("t1"),
                    "t2": signal.get("t2"),
                    "t3": signal.get("t3"),
                    "rr": signal.get("rr_t2"),
                    "retest_level": signal.get("retest_level"),
                    "daily_fibs": signal.get("daily_fibs"),
                    "four_hour_fibs": signal.get("four_hour_fibs"),
                    "five_min_fibs": signal.get("five_min_fibs"),
                    "williams_15m": signal.get("williams_15m"),
                    "williams_5m": signal.get("williams_5m"),
                    "adx_15m": signal.get("adx_15m"),
                    "option": signal.get("option"),
                })

                logger.info(
                    "%s %s score=%s price=%s",
                    asset,
                    signal["side"],
                    signal["score"],
                    signal["price"],
                )

                if should_send_signal(asset, signal["side"]):
                    send_telegram_alert(format_signal(signal))
                    record_entry_signal_sent()
                    logger.info(
                        "Daily entry signal count (IST): %s/%s | active threshold=%s",
                        DAILY_SIGNAL_STATS.get("count"), DAILY_MIN_SIGNAL_TARGET, effective_signal_threshold()
                    )
            else:
                logger.info(
                    "%s NO TRADE | long=%s short=%s | %s",
                    asset,
                    signal["long_score"],
                    signal["short_score"],
                    signal["reason"],
                )

        except Exception:
            logger.exception("Scanner error for %s", asset)


def main() -> None:
    logger.info("KRYPT BRO Signal Generator started")
    logger.info("Market data source: DELTA INDIA ONLY")
    logger.info("GOLD source: PAXGUSD")
    logger.info("Full strategy scan: NEW CLOSED 5M CANDLE ONLY")
    logger.info(
        "TRUE SCALP v2.5 | daily soft target=%s (aim 4-8, never forced) | base threshold=%s | adaptive floor=%s",
        DAILY_MIN_SIGNAL_TARGET, MIN_SIGNAL_SCORE, ADAPTIVE_MIN_SCORE
    )
    logger.info("Assets: %s", ", ".join(ASSETS))
    logger.info("Minimum score: %s", MIN_SIGNAL_SCORE)
    logger.info("Scanner: %s", "ON" if SCANNER_ENABLED else "OFF")
    logger.info("Telegram: %s", "ON" if TELEGRAM_ENABLED else "OFF")

    while True:
        scan_once()
        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    main()

# ============================================================
# STRATEGY V3 LIFECYCLE / PERFORMANCE EXTENSION
# ============================================================
# One active signal per asset. A later NO_TRADE scan never overwrites an
# active signal. Lifecycle: ACTIVE -> T1_HIT -> T2_HIT -> T3_HIT / SL_HIT.
ACTIVE_SIGNALS = {asset: None for asset in ASSETS}
SIGNAL_HISTORY = []
MAX_HISTORY = int(os.getenv("MAX_SIGNAL_HISTORY", "100"))
STATE_LOCK = threading.RLock()


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _event(record: dict):
    rec = dict(record)
    rec.setdefault("time", _utcnow())
    SIGNAL_HISTORY.insert(0, rec)
    del SIGNAL_HISTORY[MAX_HISTORY:]
    append_signal_journal(rec)


def register_active_signal(signal: dict) -> bool:
    asset = signal["asset"]
    with STATE_LOCK:
        if ACTIVE_SIGNALS.get(asset):
            logger.info("%s %s blocked: active signal already open", asset, signal.get("side"))
            return False
        rec = {
            "asset": asset, "side": signal["side"], "status": "ACTIVE",
            "score": signal["score"], "grade": signal_grade(signal["score"]),
            "entry": signal["price"], "current": signal["price"],
            "sl": signal["stop"], "t1": signal["t1"], "t2": signal["t2"], "t3": signal["t3"],
            "rr": signal.get("rr_t2"), "opened_at": _utcnow(), "updated_at": _utcnow(),
            "t1_hit": False, "t2_hit": False, "t3_hit": False, "r_multiple": 0.0,
        }
        ACTIVE_SIGNALS[asset] = rec
        _event({**rec, "event": "OPEN"})
        return True


def _r_multiple(s, price):
    risk = abs(float(s["entry"]) - float(s["sl"]))
    if risk <= 0: return 0.0
    move = (price - s["entry"]) if s["side"] == "LONG" else (s["entry"] - price)
    return round(move / risk, 3)


def update_active_signal_bar(asset: str, high: float, low: float, close: float):
    """
    Update an active signal from a fully closed 5M candle.

    IMPORTANT:
    - Target/SL detection uses candle HIGH/LOW, not only the closing price.
    - If both SL and a target are touched inside the same candle and intrabar
      ordering is unknown, use the conservative assumption: SL first.
    """
    with STATE_LOCK:
        s = ACTIVE_SIGNALS.get(asset)
        if not s:
            return

        high = float(high)
        low = float(low)
        close = float(close)

        s["current"] = close
        s["updated_at"] = _utcnow()
        s["r_multiple"] = _r_multiple(s, close)

        is_long = s["side"] == "LONG"

        if is_long:
            sl_hit = low <= float(s["sl"])
            t1_hit = high >= float(s["t1"])
            t2_hit = high >= float(s["t2"])
            t3_hit = high >= float(s["t3"])
        else:
            sl_hit = high >= float(s["sl"])
            t1_hit = low <= float(s["t1"])
            t2_hit = low <= float(s["t2"])
            t3_hit = low <= float(s["t3"])

        # Conservative handling for a candle that contains both stop and target.
        if sl_hit:
            s["status"] = "SL_HIT"
            s["current"] = float(s["sl"])
            s["r_multiple"] = -1.0
            logger.info(
                "%s %s SL HIT | entry=%s sl=%s candle_high=%s candle_low=%s",
                asset, s["side"], s["entry"], s["sl"], high, low
            )
            _event({**s, "event": "SL_HIT"})
            _event({**s, "event": "CLOSE", "closed_at": _utcnow()})
            analytics.close_trade(s, "SL_HIT", float(s["sl"]), -1.0)
            ACTIVE_SIGNALS[asset] = None
            send_telegram_alert(
                f"🛑 <b>KRYPT BRO • {asset} {s['side']} SL HIT</b>\\n"
                f"Entry: <b>${s['entry']:,.2f}</b>\\n"
                f"SL: <b>${s['sl']:,.2f}</b>\\n"
                f"Result: <b>-1.00R</b>"
            )
            return

        targets = (
            ("t1_hit", t1_hit, "T1_HIT", s["t1"]),
            ("t2_hit", t2_hit, "T2_HIT", s["t2"]),
            ("t3_hit", t3_hit, "T3_HIT", s["t3"]),
        )

        for key, hit, label, level in targets:
            if hit and not s[key]:
                s[key] = True
                s["status"] = label
                # R at exact target level is more meaningful than candle close.
                s["r_multiple"] = _r_multiple(s, float(level))
                logger.info(
                    "%s %s %s | entry=%s target=%s candle_high=%s candle_low=%s",
                    asset, s["side"], label, s["entry"], level, high, low
                )
                _event({**s, "event": label})
                analytics.event(label, s)
                send_telegram_alert(
                    f"🎯 <b>KRYPT BRO • {asset} {s['side']} {label.replace('_',' ')}</b>\\n"
                    f"Entry: <b>${s['entry']:,.2f}</b>\\n"
                    f"Target: <b>${float(level):,.2f}</b>\\n"
                    f"Result: <b>{s['r_multiple']:+.2f}R</b>"
                )

        if t3_hit:
            s["status"] = "T3_HIT"
            s["current"] = float(s["t3"])
            s["r_multiple"] = _r_multiple(s, float(s["t3"]))
            _event({**s, "event": "CLOSE", "closed_at": _utcnow()})
            analytics.close_trade(s, "T3_HIT", float(s["t3"]), s["r_multiple"])
            ACTIVE_SIGNALS[asset] = None


def update_active_signal(asset: str, price: float):
    """Compatibility helper for callers that only have one price."""
    update_active_signal_bar(asset, price, price, price)


def active_signal_snapshot():
    with STATE_LOCK: return {k:(dict(v) if v else None) for k,v in ACTIVE_SIGNALS.items()}


def signal_history(limit=30):
    with STATE_LOCK: return [dict(x) for x in SIGNAL_HISTORY[:max(1,min(int(limit),100))]]


def performance_stats():
    closed = [x for x in SIGNAL_HISTORY if x.get("event") == "CLOSE"]
    if not closed: return {"closed":0,"wins":0,"losses":0,"win_rate":None,"total_r":0.0,"avg_r":None}
    rs = [float(x.get("r_multiple",0)) for x in closed]
    wins = sum(r > 0 for r in rs); losses = sum(r <= 0 for r in rs)
    return {"closed":len(rs),"wins":wins,"losses":losses,"win_rate":round(wins/len(rs)*100,1),"total_r":round(sum(rs),2),"avg_r":round(sum(rs)/len(rs),2)}

# Wrap original scanner so lifecycle prices are checked every loop and new
# signals are locked before Telegram delivery. Existing strategy calculation
# remains unchanged.
_original_scan_once = scan_once

def scan_once() -> None:
    # Update active signals from lightweight latest 5M/public data first.
    for asset in ASSETS:
        try:
            c = get_latest_closed_5m(asset)
            if c is not None:
                update_active_signal_bar(
                    asset,
                    high=float(c["high"]),
                    low=float(c["low"]),
                    close=float(c["close"]),
                )
        except Exception:
            logger.exception("Lifecycle price update failed for %s", asset)

    # Temporarily intercept duplicate sends: the original scanner may produce
    # SIGNAL, then we reconcile it into ACTIVE state below.
    before = {a: LATEST_STATUS[a].get("updated_at") for a in ASSETS}
    _original_scan_once()
    for asset in ASSETS:
        l = LATEST_STATUS[asset]
        changed = l.get("updated_at") != before.get(asset)

        if changed and l.get("status") == "SIGNAL":
            sig = {
                "asset": asset,
                "side": l.get("side"),
                "score": l.get("score"),
                "price": l.get("price"),
                "stop": l.get("stop"),
                "t1": l.get("t1"),
                "t2": l.get("t2"),
                "t3": l.get("t3"),
                "rr_t2": l.get("rr"),
            }
            if ACTIVE_SIGNALS.get(asset) is None:
                registered = register_active_signal(sig)
                if registered:
                    logger.info(
                        "%s %s lifecycle OPEN | entry=%s sl=%s t1=%s t2=%s t3=%s",
                        asset, sig["side"], sig["price"], sig["stop"],
                        sig["t1"], sig["t2"], sig["t3"]
                    )

        # Always preserve active lifecycle on the dashboard, even if the
        # strategy scanner did not run or just returned NO_TRADE.
        s = ACTIVE_SIGNALS.get(asset)
        if s:
            LATEST_STATUS[asset].update({
                "status": s["status"],
                "side": s["side"],
                "score": s["score"],
                "grade": s["grade"],
                "price": s["current"],
                "stop": s["sl"],
                "t1": s["t1"],
                "t2": s["t2"],
                "t3": s["t3"],
                "rr": s["rr"],
                "reason": f"ACTIVE • {s['r_multiple']:+.2f}R",
                "updated_at": s["updated_at"],
            })
