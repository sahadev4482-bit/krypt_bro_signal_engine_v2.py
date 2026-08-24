# KRYPT BRO SIGNAL ENGINE v3 - DELTA ONLY + GOLD + LOW LOAD
# Pure signal generation first.
# Includes: Daily + 5M Fib R1-R5/S1-S5, 1H/15M/5M MTF,
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
from datetime import datetime, timezone

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

MIN_SIGNAL_SCORE = int(os.getenv("MIN_SIGNAL_SCORE", "75"))
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "900"))

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

DELTA_BASE_URL = "https://api.india.delta.exchange"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
import analytics_store as analytics

logger = logging.getLogger("krypt_bro")

LAST_SIGNAL = {asset: {"side": None, "time": 0} for asset in ASSETS}

# Full strategy runs only once per newly closed 5-minute candle.
# This drastically reduces REST load compared with recalculating all
# 1D/1H/15M/5M data every 20 seconds.
LAST_PROCESSED_5M_CLOSE = {asset: None for asset in ASSETS}
PENDING_SIGNALS = {asset: None for asset in ASSETS}

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
        "five_min_fibs": {},
        "confluence": {},
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


def fib_context_for_side(side: str, price: float, daily: dict, five_min: dict) -> dict:
    """
    Direction-aware Fib context.
    LONG prefers nearby support/pivot below price.
    SHORT prefers nearby resistance/pivot above price.
    """
    tolerance = price * (FIB_NEAR_PCT / 100.0)

    if side == "LONG":
        d_candidates = [(k, v) for k, v in daily.items() if (k.startswith("S") or k == "P") and v <= price + tolerance]
        m_candidates = [(k, v) for k, v in five_min.items() if (k.startswith("S") or k == "P") and v <= price + tolerance]
    else:
        d_candidates = [(k, v) for k, v in daily.items() if (k.startswith("R") or k == "P") and v >= price - tolerance]
        m_candidates = [(k, v) for k, v in five_min.items() if (k.startswith("R") or k == "P") and v >= price - tolerance]

    def nearest(candidates):
        if not candidates:
            return None, None
        return min(candidates, key=lambda item: abs(price - item[1]))

    d_name, d_value = nearest(d_candidates)
    m_name, m_value = nearest(m_candidates)

    paired = (
        d_value is not None and m_value is not None
        and abs(d_value - m_value) <= tolerance
    )

    return {
        "daily_name": d_name,
        "daily_value": d_value,
        "five_name": m_name,
        "five_value": m_value,
        "paired": paired,
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
    """
    Keeps an unconfirmed setup alive for a few closed 5M candles.
    If not confirmed in SIGNAL_EXPIRY_CANDLES, expire it.
    """
    current_close = setup.get("candle_close")
    pending = PENDING_SIGNALS.get(asset)

    if setup.get("retest_confirmed"):
        PENDING_SIGNALS[asset] = None
        return {"allowed": True, "state": "CONFIRMED"}

    if pending is None or pending.get("side") != side:
        PENDING_SIGNALS[asset] = {
            "side": side,
            "first_close": current_close,
            "age": 1,
        }
        return {"allowed": False, "state": "WAITING_RETEST"}

    pending["age"] += 1
    if pending["age"] > SIGNAL_EXPIRY_CANDLES:
        PENDING_SIGNALS[asset] = None
        return {"allowed": False, "state": "EXPIRED"}

    return {"allowed": False, "state": "WAITING_RETEST"}


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(asset: str) -> dict | None:
    df_1d = fetch_candles(asset, "1d", 10)
    df_1h = fetch_candles(asset, "1h", 120)
    df_15m = fetch_candles(asset, "15m", 150)
    df_5m = fetch_candles(asset, "5m", 200)

    if any(df.empty for df in [df_1d, df_1h, df_15m, df_5m]):
        return None

    df_1h = add_ema(df_1h, [20, 50])
    df_15m = add_rsi(add_ema(df_15m, [9, 21]), 14)
    df_5m = add_atr(add_rsi(add_ema(df_5m, [9, 21]), 14), 14)

    # IMPORTANT: select the newest fully CLOSED candle by close_time,
    # rather than assuming the second-last row is always the closed one.
    now_utc = pd.Timestamp.now(tz="UTC")

    h1_closed = df_1h[df_1h["close_time"] <= now_utc]
    m15_closed = df_15m[df_15m["close_time"] <= now_utc]
    m5_closed = df_5m[df_5m["close_time"] <= now_utc]

    if h1_closed.empty or m15_closed.empty or m5_closed.empty:
        return None

    h1 = h1_closed.iloc[-1]
    m15 = m15_closed.iloc[-1]
    m5 = m5_closed.iloc[-1]

    current_price = float(m5["close"])

    # Never create a new signal from stale data.
    if not candle_is_fresh(m5):
        logger.warning("%s: stale 5M candle; signal skipped", asset)
        return None

    daily_fibs = get_daily_fib_levels(df_1d)
    five_min_fibs = get_5m_fib_levels(df_5m)

    if not daily_fibs or not five_min_fibs:
        return None

    structure = recent_structure(df_5m, 8)
    confluence = fib_confluence(current_price, daily_fibs, five_min_fibs)

    # ---------- Direction ----------
    h1_bull = h1["ema_20"] > h1["ema_50"] and h1["close"] > h1["ema_20"]
    h1_bear = h1["ema_20"] < h1["ema_50"] and h1["close"] < h1["ema_20"]

    m15_bull = m15["ema_9"] > m15["ema_21"] and m15["rsi"] >= 52
    m15_bear = m15["ema_9"] < m15["ema_21"] and m15["rsi"] <= 48

    m5_bull = m5["ema_9"] > m5["ema_21"] and m5["close"] > m5["ema_9"]
    m5_bear = m5["ema_9"] < m5["ema_21"] and m5["close"] < m5["ema_9"]

    # ---------- Volume ----------
    closed_5m = df_5m[df_5m["close_time"] <= now_utc]
    vol_avg_20 = float(closed_5m["volume"].tail(20).mean())
    volume_ok = float(m5["volume"]) >= vol_avg_20 * VOLUME_MULTIPLIER

    # ---------- Score ----------
    long_score = 0
    short_score = 0

    # 1H trend = 20
    if h1_bull:
        long_score += 20
    if h1_bear:
        short_score += 20

    # 15M setup = 15
    if m15_bull:
        long_score += 15
    if m15_bear:
        short_score += 15

    # 5M trigger = 20
    if m5_bull:
        long_score += 20
    if m5_bear:
        short_score += 20

    # Volume = 15
    if volume_ok:
        long_score += 15
        short_score += 15

    # RSI quality = 10
    if 55 <= m15["rsi"] <= 72:
        long_score += 10
    if 28 <= m15["rsi"] <= 45:
        short_score += 10

    # Structure = 10
    if structure == "BULLISH":
        long_score += 10
    elif structure == "BEARISH":
        short_score += 10

    # Fib confluence = 10
    if confluence["paired"]:
        long_score += 10
        short_score += 10
    elif confluence["near_daily"] and confluence["near_5m"]:
        long_score += 8
        short_score += 8
    elif confluence["near_daily"] or confluence["near_5m"]:
        long_score += 4
        short_score += 4

    # ---------- Sideways filter ----------
    ema_gap_pct = abs(m5["ema_9"] - m5["ema_21"]) / current_price * 100
    atr_pct = float(m5["atr"]) / current_price * 100

    choppy = ema_gap_pct < 0.03 and atr_pct < MIN_ATR_PCT
    volatility_invalid = atr_pct < MIN_ATR_PCT or atr_pct > MAX_ATR_PCT
    ema_extension_atr = abs(current_price - float(m5["ema_9"])) / max(float(m5["atr"]), 1e-9)
    overextended = ema_extension_atr > MAX_EMA_EXTENSION_ATR

    if choppy or volatility_invalid or overextended:
        return {
            "asset": asset,
            "status": "NO_TRADE",
            "reason": "Choppy / volatility invalid / overextended",
            "price": current_price,
            "long_score": long_score,
            "short_score": short_score,
            "daily_fibs": daily_fibs,
            "five_min_fibs": five_min_fibs,
            "confluence": confluence,
        }

    if long_score >= MIN_SIGNAL_SCORE and long_score > short_score:
        side = "LONG"
        score = long_score
    elif short_score >= MIN_SIGNAL_SCORE and short_score > long_score:
        side = "SHORT"
        score = short_score
    else:
        return {
            "asset": asset,
            "status": "NO_TRADE",
            "reason": "Score below threshold",
            "price": current_price,
            "long_score": long_score,
            "short_score": short_score,
            "daily_fibs": daily_fibs,
            "five_min_fibs": five_min_fibs,
            "confluence": confluence,
        }

    side_fib = fib_context_for_side(side, current_price, daily_fibs, five_min_fibs)

    # High-quality scalping signal requires volume confirmation.
    if REQUIRE_VOLUME_FOR_SIGNAL and not volume_ok:
        return {
            "asset": asset,
            "status": "NO_TRADE",
            "reason": "Volume confirmation missing",
            "price": current_price,
            "long_score": long_score,
            "short_score": short_score,
            "daily_fibs": daily_fibs,
            "five_min_fibs": five_min_fibs,
            "confluence": side_fib,
        }

    atr_now = float(m5["atr"])
    retest_info = breakout_retest_status(df_5m, side, atr_now)
    gate = pending_signal_gate(
        asset,
        side,
        {
            "retest_confirmed": retest_info["confirmed"],
            "candle_close": str(m5["close_time"]),
        },
    )

    if not gate["allowed"]:
        return {
            "asset": asset,
            "status": "NO_TRADE",
            "reason": f"{gate['state']}: {retest_info['reason']}",
            "price": current_price,
            "long_score": long_score,
            "short_score": short_score,
            "daily_fibs": daily_fibs,
            "five_min_fibs": five_min_fibs,
            "confluence": side_fib,
        }

    # Require at least one directionally meaningful Fib reference.
    if side_fib["daily_name"] is None and side_fib["five_name"] is None:
        return {
            "asset": asset,
            "status": "NO_TRADE",
            "reason": "No direction-aware Fib context",
            "price": current_price,
            "long_score": long_score,
            "short_score": short_score,
            "daily_fibs": daily_fibs,
            "five_min_fibs": five_min_fibs,
            "confluence": confluence,
        }

    atr = float(m5["atr"])
    swing_low = float(closed_5m["low"].tail(6).min())
    swing_high = float(closed_5m["high"].tail(6).max())

    if side == "LONG":
        atr_sl = current_price - ATR_SL_MULTIPLIER * atr
        stop = min(swing_low, atr_sl)
        risk = current_price - stop

        if risk <= 0:
            return None

        t1 = current_price + risk
        t2 = current_price + MIN_RR * risk
        t3 = current_price + 2.5 * risk

    else:
        atr_sl = current_price + ATR_SL_MULTIPLIER * atr
        stop = max(swing_high, atr_sl)
        risk = stop - current_price

        if risk <= 0:
            return None

        t1 = current_price - risk
        t2 = current_price - MIN_RR * risk
        t3 = current_price - 2.5 * risk

    rr_t2 = reward_risk(current_price, stop, t2, side)
    if rr_t2 + 1e-9 < MIN_RR:
        return {
            "asset": asset,
            "status": "NO_TRADE",
            "reason": f"R:R below minimum ({rr_t2:.2f})",
            "price": current_price,
            "long_score": long_score,
            "short_score": short_score,
            "daily_fibs": daily_fibs,
            "five_min_fibs": five_min_fibs,
            "confluence": confluence,
        }

    return {
        "asset": asset,
        "status": "SIGNAL",
        "side": side,
        "score": score,
        "price": round(current_price, 2),
        "stop": round(stop, 2),
        "t1": round(t1, 2),
        "t2": round(t2, 2),
        "t3": round(t3, 2),
        "rsi_15m": round(float(m15["rsi"]), 1),
        "volume_ok": volume_ok,
        "structure": structure,
        "daily_fibs": daily_fibs,
        "five_min_fibs": five_min_fibs,
        "confluence": side_fib,
        "rr_t2": round(rr_t2, 2),
        "retest_confirmed": True,
        "retest_level": retest_info.get("level"),
        "h1_bull": h1_bull,
        "h1_bear": h1_bear,
        "m15_bull": m15_bull,
        "m15_bear": m15_bear,
        "m5_bull": m5_bull,
        "m5_bear": m5_bear,
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

    daily_text = (
        f"{c['daily_name']} ${c['daily_value']:,.2f}"
        if c["daily_name"] and c["daily_value"] is not None
        else "N/A"
    )
    five_text = (
        f"{c['five_name']} ${c['five_value']:,.2f}"
        if c["five_name"] and c["five_value"] is not None
        else "N/A"
    )

    return (
        f"🔥 <b>KRYPT BRO SIGNAL</b>\n\n"
        f"{side_icon} <b>{asset} {side}</b>\n"
        f"Quality: <b>{quality}</b>\n"
        f"Score: <b>{signal['score']}/100</b>\n\n"
        f"Entry: <b>${signal['price']:,.2f}</b>\n"
        f"SL: <b>${signal['stop']:,.2f}</b>\n"
        f"T1: <b>${signal['t1']:,.2f}</b>\n"
        f"T2: <b>${signal['t2']:,.2f}</b>\n"
        f"T3: <b>${signal['t3']:,.2f}</b>\n"
        f"R:R to T2: <b>1:{signal['rr_t2']:.2f}</b>\n\n"
        f"1H Trend: {'✅' if (signal['h1_bull'] if side == 'LONG' else signal['h1_bear']) else '❌'}\n"
        f"15M Setup: {'✅' if (signal['m15_bull'] if side == 'LONG' else signal['m15_bear']) else '❌'}\n"
        f"5M Trigger: {'✅' if (signal['m5_bull'] if side == 'LONG' else signal['m5_bear']) else '❌'}\n"
        f"Volume: {'✅' if signal['volume_ok'] else '❌'}\n"
        f"Structure: <b>{signal['structure']}</b>\n"
        f"15M RSI: <b>{signal['rsi_15m']}</b>\n\n"
        f"Daily Fib Near: <b>{daily_text}</b>\n"
        f"5M Fib Near: <b>{five_text}</b>\n"
        f"Fib Confluence: <b>{'🔥 YES' if c['paired'] else 'NO'}</b>"
    )


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
                    "five_min_fibs": signal.get("five_min_fibs", {}),
                    "confluence": signal.get("confluence", {}),
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
                    "five_min_fibs": signal.get("five_min_fibs", {}),
                    "confluence": signal.get("confluence", {}),
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
                    "five_min_fibs": signal.get("five_min_fibs"),
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
