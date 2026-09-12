"""KRYPT BRO Telegram read-only command listener.

Adds manual Delta option-premium ladder commands without touching the scanner,
signal lifecycle, trading runtime, or existing outbound Telegram alerts.

Commands:
  /btc          BTC nearest-expiry option ladder
  /eth          ETH nearest-expiry option ladder
  /gold         GOLD nearest-expiry option ladder
  /options      BTC + ETH + GOLD ladders
  /option BTC   Generic single-asset ladder command
  /help         Command help
"""
from __future__ import annotations

import html
import threading
import time
from typing import Optional

import requests

from backend import signal_engine as eng

_POLL_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()


def _allowed_chat(chat_id) -> bool:
    """Restrict command replies to configured TELEGRAM_CHAT_ID when present."""
    configured = str(getattr(eng, "TELEGRAM_CHAT_ID", "") or "").strip()
    if not configured:
        return True
    return str(chat_id) == configured


def _send(chat_id, text: str) -> None:
    token = str(getattr(eng, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    if not token:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=12,
        )
        if not r.ok:
            eng.logger.warning("Telegram command reply failed %s: %s", r.status_code, r.text[:250])
    except Exception as exc:
        eng.logger.warning("Telegram command reply exception: %s", exc)


def _latest_underlying_price(asset: str) -> float | None:
    """Use latest Delta 1m candle close as a lightweight public underlying price."""
    try:
        df = eng.fetch_candles(asset, "1m", count=3)
        if df is None or df.empty:
            return None
        value = float(df.iloc[-1]["close"])
        return value if value > 0 else None
    except Exception as exc:
        eng.logger.warning("%s manual option spot fetch failed: %s", asset, exc)
        return None


def _fmt_num(value, decimals=2) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
        if abs(v) >= 1000:
            return f"{v:,.{decimals}f}"
        if abs(v) >= 1:
            return f"{v:.{decimals}f}"
        return f"{v:.4f}"
    except Exception:
        return "—"


def build_ladder_message(asset: str) -> str:
    asset = asset.upper().strip()
    if asset not in eng.ASSETS:
        return "❌ Supported assets: <b>BTC, ETH, GOLD</b>"

    spot = _latest_underlying_price(asset)
    if spot is None:
        return f"⚠️ <b>{asset} OPTION CHAIN</b>\nUnderlying price unavailable from Delta right now."

    chain = eng.fetch_delta_option_chain(asset)
    if not chain:
        return (
            f"⚠️ <b>{asset} OPTION CHAIN</b>\n"
            f"Spot: <b>{_fmt_num(spot)}</b>\n"
            "Delta option premium data unavailable right now. Core scanner is unaffected."
        )

    snap = eng.build_option_chain_snapshot(asset, spot, chain=chain, wing_count=4)
    if not snap or not snap.get("rows"):
        return (
            f"⚠️ <b>{asset} OPTION CHAIN</b>\n"
            f"Spot: <b>{_fmt_num(spot)}</b>\n"
            "Nearest-expiry ladder could not be built from the current contracts."
        )

    title = f"📊 <b>{html.escape(asset)} DELTA OPTIONS</b>"
    lines = [
        title,
        f"Spot: <b>{_fmt_num(snap.get('spot'))}</b>",
        f"ATM: <b>{_fmt_num(snap.get('atm_strike'))}</b>",
        f"Expiry: <b>{html.escape(str(snap.get('expiry') or '—'))}</b>",
        "",
        "<b>CALL            STRIKE             PUT</b>",
    ]

    for row in snap.get("rows", []):
        call = _fmt_num(row.get("call_premium"))
        strike = _fmt_num(row.get("strike"))
        put = _fmt_num(row.get("put_premium"))
        atm = "  ◀ ATM" if row.get("is_atm") else ""
        lines.append(f"<code>{call:>10}  {strike:>14}  {put:>10}</code>{atm}")

    lines.extend([
        "",
        "Premium = <b>best ask</b> when available, otherwise mark price.",
        "Read-only display; no order is placed.",
    ])
    return "\n".join(lines)



def build_daily_analysis_message():
    st=eng.analytics.daily_summary()
    if not st.get("closed"):
        return f"📈 <b>KRYPT BRO DAILY • {st.get('date')}</b>\\nClosed signals: <b>0</b>"
    lines=[f"📈 <b>KRYPT BRO DAILY • {st['date']}</b>","",f"Closed: <b>{st['closed']}</b> | Success: <b>{st['wins']}</b> | Fail: <b>{st['losses']}</b>",f"Win rate: <b>{st['win_rate']:.1f}%</b> | Net: <b>{st['total_r']:+.2f}R</b> | Avg: <b>{st['avg_r']:+.2f}R</b>",f"T1: <b>{st['t1_rate']:.1f}%</b> | T2: <b>{st['t2_rate']:.1f}%</b> | T3: <b>{st['t3_rate']:.1f}%</b>","", "<b>BY ASSET</b>"]
    for asset,x in st["by_asset"].items(): lines.append(f"{asset}: {x['trades']} • {x['wins']}W/{x['losses']}L • {x['win_rate']:.1f}% • {x['total_r']:+.2f}R")
    return "\\n".join(lines)

def _help_message() -> str:
    return (
        "🤖 <b>KRYPT BRO OPTION COMMANDS</b>\n\n"
        "/btc — BTC option premiums\n"
        "/eth — ETH option premiums\n"
        "/gold — GOLD option premiums\n"
        "/options — BTC + ETH + GOLD\n"
        "/option BTC — generic asset command\n"
        "/daily — today success/fail analysis\n"
        "/help — show commands\n\n"
        "Each ladder shows nearest expiry, ATM and up to 4 strikes below + 4 above."
    )


def _parse_command(text: str) -> tuple[str | None, str | None]:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None, None
    parts = raw.split()
    cmd = parts[0].split("@", 1)[0].lower()
    arg = parts[1].upper() if len(parts) > 1 else None
    return cmd, arg


def handle_text(chat_id, text: str) -> bool:
    """Handle one Telegram command. Returns True when recognized."""
    cmd, arg = _parse_command(text)
    if not cmd:
        return False

    mapping = {"/btc": "BTC", "/eth": "ETH", "/gold": "GOLD"}
    if cmd in mapping:
        _send(chat_id, build_ladder_message(mapping[cmd]))
        return True

    if cmd == "/option":
        if arg in eng.ASSETS:
            _send(chat_id, build_ladder_message(arg))
        else:
            _send(chat_id, "Usage: <code>/option BTC</code> or ETH / GOLD")
        return True

    if cmd == "/options":
        # Separate messages keep each ladder readable and below Telegram limits.
        for asset in eng.ASSETS:
            _send(chat_id, build_ladder_message(asset))
        return True

    if cmd == "/daily":
        _send(chat_id, build_daily_analysis_message())
        return True

    if cmd in ("/help", "/start"):
        _send(chat_id, _help_message())
        return True

    return False


def _poll_loop() -> None:
    token = str(getattr(eng, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    if not token:
        eng.logger.info("Telegram command listener disabled: TELEGRAM_BOT_TOKEN missing")
        return

    base = f"https://api.telegram.org/bot{token}"
    offset = None

    # Ensure long polling can receive updates if an old webhook was ever configured.
    try:
        requests.post(f"{base}/deleteWebhook", json={"drop_pending_updates": False}, timeout=10)
    except Exception:
        pass

    eng.logger.info("Telegram command listener started: /btc /eth /gold /options /option /daily")

    while not _STOP.is_set():
        try:
            params = {"timeout": 25, "allowed_updates": '["message"]'}
            if offset is not None:
                params["offset"] = offset
            r = requests.get(f"{base}/getUpdates", params=params, timeout=32)
            if not r.ok:
                eng.logger.warning("Telegram getUpdates HTTP %s", r.status_code)
                time.sleep(3)
                continue
            payload = r.json() if r.content else {}
            for update in payload.get("result", []) if isinstance(payload, dict) else []:
                try:
                    offset = int(update.get("update_id", 0)) + 1
                    msg = update.get("message") or {}
                    chat = msg.get("chat") or {}
                    chat_id = chat.get("id")
                    text = msg.get("text") or ""
                    if chat_id is None or not _allowed_chat(chat_id):
                        continue
                    handle_text(chat_id, text)
                except Exception as exc:
                    eng.logger.warning("Telegram update handling failed: %s", exc)
        except requests.exceptions.ReadTimeout:
            continue
        except Exception as exc:
            eng.logger.warning("Telegram command polling error: %s", exc)
            time.sleep(3)


def start() -> None:
    """Start once as a daemon; safe to call from app startup."""
    global _POLL_THREAD
    if _POLL_THREAD and _POLL_THREAD.is_alive():
        return
    _STOP.clear()
    _POLL_THREAD = threading.Thread(target=_poll_loop, name="telegram-option-commands", daemon=True)
    _POLL_THREAD.start()
