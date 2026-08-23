KRYPT BRO Dashboard
===================
Files:
- app.py
- signal_engine.py
- requirements.txt
- render.yaml

Render:
Build command: pip install -r requirements.txt
Start command: python app.py

Environment variables (optional):
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
RENDER_EXTERNAL_URL
MIN_SIGNAL_SCORE=75
MIN_RR=1.80

Dashboard v2:
- MIN_RR locked at 1.80
- T1 = 1R, T2 = 1.8R, T3 = 2.5R
- Signal grades A+ / A / B / NO TRADE
- Daily Fib Pivot P, R1-R5, S1-S5
- 5M Fib Pivot P, R1-R5, S1-S5

V3 ONE-DEPLOY STRATEGY UPDATE
- R:R floating-point edge fixed
- MIN_RR default 1.80
- Volume confirmation mandatory for actionable signal
- Breakout/Breakdown + retest confirmation
- Pending setup expires after 3 closed 5M candles
- JSONL signal journal for later analysis
- Existing Delta-only, BTC/ETH/GOLD, Daily+5M Fib pivots retained
