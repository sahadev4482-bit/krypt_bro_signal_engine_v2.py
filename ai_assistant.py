import json
import os
from typing import Any, Dict, List

import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "stealth/ox-alpha").strip()
AI_CHAT_ENABLED = os.getenv("AI_CHAT_ENABLED", "true").lower() == "true"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are KRYPT BRO AI Assistant, a read-only market-analysis assistant embedded inside a crypto signal dashboard.

Rules:
- You may explain live prices, signal states, scores, trends, Fib levels, volume, RSI, active signal lifecycle, positions summary, and backtest/performance data that the application supplies.
- Never claim access to data that is absent from the supplied application context.
- Never expose or request API keys, API secrets, Telegram tokens, TOTP secrets, passwords, or environment variables.
- You do NOT place orders and must not imply that you placed an order.
- Treat strategy score as a setup score, not as a probability or guaranteed win rate.
- Clearly distinguish NO_TRADE / WAITING_RETEST / ACTIVE / T1_HIT / T2_HIT / T3_HIT / SL_HIT.
- Be concise and practical.
- Reply in the user's language. Malayalam questions should receive Malayalam answers, while keeping technical terms understandable.
- Avoid guaranteeing profitability. Mention risk when leverage or live trading is discussed.
"""

def status():
    return {
        "enabled": AI_CHAT_ENABLED,
        "configured": bool(OPENROUTER_API_KEY),
        "model": AI_MODEL,
        "mode": "READ_ONLY",
    }

def _safe_json(data: Any, max_chars: int = 18000) -> str:
    text = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    return text[:max_chars]

def ask(message: str, context: Dict[str, Any], history: List[Dict[str, str]] | None = None) -> str:
    if not AI_CHAT_ENABLED:
        raise RuntimeError("AI chat is disabled.")
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured in Render.")

    clean_message = (message or "").strip()
    if not clean_message:
        raise ValueError("Message is empty.")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        for item in history[-6:]:
            role = item.get("role")
            content = str(item.get("content", ""))[:2000]
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({
        "role": "system",
        "content": "CURRENT KRYPT BRO APPLICATION CONTEXT:\n" + _safe_json(context),
    })
    messages.append({"role": "user", "content": clean_message[:4000]})

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 900,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("APP_PUBLIC_URL", "https://krypt-bro-signal-engine-v2-py.onrender.com"),
        "X-Title": "KRYPT BRO AI Assistant",
    }

    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=45)
    try:
        data = response.json()
    except Exception:
        data = {}

    if not response.ok:
        detail = data.get("error", {}).get("message") if isinstance(data, dict) else None
        raise RuntimeError(detail or f"AI provider returned HTTP {response.status_code}")

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("AI provider returned no answer.")

    content = choices[0].get("message", {}).get("content")
    if isinstance(content, list):
        content = "\n".join(
            str(x.get("text", "")) for x in content if isinstance(x, dict)
        )
    return (content or "").strip()
