KRYPT BRO V4 REAL FIX

ROOT CAUSE OF EMPTY TICKS:
Delta new public `trades` messages use `sy` for the product symbol:
{"p":"72141.5","sy":"BTCUSD","type":"trades"}.
The previous parser did not read `sy`, so WS could say connected while quotes stayed null.

FIXES:
1. delta_ws.py now parses `sy`.
2. Logs first valid tick as: LIVE TICK READY | BTC BTCUSD = ...
3. Browser now uses SSE /api/live/stream; no 500ms /api/live GET spam.
4. BTC/ETH/GOLD live strip shows real pushed price, direction arrow, age and parsed tick count.
5. Local SVG emblems added for BTC/ETH/GOLD and popular tokens.
6. Robot AI is directly below Settings, before bottom system-status cards.
7. CHAT button opens the actual AI chat panel adjacent to sidebar.
8. Existing POST /api/ai/chat flow preserved.
9. Signal engine/Telegram/trading lifecycle unchanged.
