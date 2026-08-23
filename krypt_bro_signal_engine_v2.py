# KRYPT BRO SIGNAL ENGINE v2
# Pure signal generation first.
# Includes: Daily + 5M Fib R1-R5/S1-S5, 1H/15M/5M MTF,
# closed-candle checks, stale-data rejection, ATR/EMA extension filters,
# directional Fib context, minimum R:R, cooldown and Telegram ON/OFF.
#
import os
import time
import math
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

# ============================================================
# KRYPT BRO - PURE SIGNAL GENERATOR
# No order placement. No leverage. No exchange trading API.
# Data: Binance public market data
# Alerts: Telegram (optional)
# ============================================================

ASSETS = ["BTC", "ETH"]
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "20"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MIN_SIGNAL_SCORE = int(os.getenv("MIN_SIGNAL_SCORE", "75"))
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "900"))

# Scanner / Telegram runtime controls
SCANNER_ENABLED = True
TELEGRAM_ENABLED = True

# Signal quality safeguards
MIN_RR = float(os.getenv("MIN_RR", "1.50"))
MAX_SIGNAL_AGE_SECONDS = int(os.getenv("MAX_SIGNAL_AGE_SECONDS", "90"))
MIN_ATR_PCT = float(os.getenv("MIN_ATR_PCT", "0.08"))
MAX_ATR_PCT = float(os.getenv("MAX_ATR_PCT", "2.50"))
MAX_EMA_EXTENSION_ATR = float(os.getenv("MAX_EMA_EXTENSION_ATR", "1.50"))

# Fib confluence tolerance as % of price
FIB_NEAR_PCT = float(os.getenv("FIB_NEAR_PCT", "0.20"))

# Volume confirmation
VOLUME_MULTIPLIER = float(os.getenv("VOLUME_MULTIPLIER", "1.05"))

# ATR-based risk
ATR_SL_MULTIPLIER = float(os.getenv("ATR_SL_MULTIPLIER", "1.20"))

BINANCE_BASE_URL = "https://api.binance.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("krypt_bro")

LAST_SIGNAL = {asset: {"side": None, "time": 0} for asset in ASSETS}


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
    symbol = f"{asset}USDT"
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": count}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        rows = response.json()

        df = pd.DataFrame(
            rows,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ],
        )

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        return df.dropna().reset_index(drop=True)

    except Exception:
        logger.exception("Failed to fetch %s %s candles", asset, interval)
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
    # Last row can be today's still-forming daily candle.
    # Therefore use previous fully closed daily candle.
    if len(df_1d) < 2:
        return {}

    candle = df_1d.iloc[-2]
    return fibonacci_pivots(
        float(candle["high"]),
        float(candle["low"]),
        float(candle["close"]),
    )


def get_5m_fib_levels(df_5m: pd.DataFrame) -> dict:
    # Previous fully closed 5-minute candle only.
    if len(df_5m) < 2:
        return {}

    candle = df_5m.iloc[-2]
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
    closed = df.iloc[:-1].tail(lookback)
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

    # IMPORTANT: use last fully CLOSED candles for signal decisions.
    h1 = df_1h.iloc[-2]
    m15 = df_15m.iloc[-2]
    m5 = df_5m.iloc[-2]

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
    closed_5m = df_5m.iloc[:-1]
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
        t2 = current_price + 1.5 * risk
        t3 = current_price + 2.0 * risk

    else:
        atr_sl = current_price + ATR_SL_MULTIPLIER * atr
        stop = max(swing_high, atr_sl)
        risk = stop - current_price

        if risk <= 0:
            return None

        t1 = current_price - risk
        t2 = current_price - 1.5 * risk
        t3 = current_price - 2.0 * risk

    rr_t2 = reward_risk(current_price, stop, t2, side)
    if rr_t2 < MIN_RR:
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
        "h1_bull": h1_bull,
        "h1_bear": h1_bear,
        "m15_bull": m15_bull,
        "m15_bear": m15_bear,
        "m5_bull": m5_bull,
        "m5_bear": m5_bear,
    }


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
            signal = calculate_signal(asset)
            if not signal:
                continue

            if signal["status"] == "SIGNAL":
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
    logger.info("Assets: %s", ", ".join(ASSETS))
    logger.info("Minimum score: %s", MIN_SIGNAL_SCORE)
    logger.info("Scanner: %s", "ON" if SCANNER_ENABLED else "OFF")
    logger.info("Telegram: %s", "ON" if TELEGRAM_ENABLED else "OFF")

    while True:
        scan_once()
        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
