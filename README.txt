KRYPT BRO FULLSTACK STRUCTURE

Backend:
- app.py
- signal_engine.py

Frontend:
- templates/index.html
- static/css/style.css
- static/js/app.js

Render:
Build command: pip install -r requirements.txt
Start command: python app.py

UI:
- deep sky-blue/cyan/teal glass
- separate CSS lighting/animation
- no black background
- no heavy live chart
- BTC/ETH/GOLD signal cards
- Daily + 5M Fib pivots
- 40-token compact table placeholder
- TOTP UI placeholder for future trading auth

LOCKED UI + LIVE TOKEN DATA
- Locked robotic single-screen HUD retained
- Delta public GET /v2/tickers used for token live rates
- One backend ticker call cached for 4 seconds
- 40 tokens shown as 4 groups x 10
- No 40 separate REST calls
- Token rate + 24h move (when supplied/derivable) + lightweight movement score/status
- Token strategy signals are NOT yet the full BTC/ETH/GOLD MTF strategy

SINGLE DEPLOY TRADING LAYER

Render Environment Variables:
DELTA_API_KEY=<your trading api key>
DELTA_API_SECRET=<your api secret>
DELTA_TRADING_ENABLED=false

First deploy with DELTA_TRADING_ENABLED=false.
Verify Positions/API connectivity.
Then set DELTA_TRADING_ENABLED=true only when ready for LIVE manual orders.

Features:
- HMAC-SHA256 signed Delta India REST requests
- API credentials remain server-side only
- Manual market BUY / SELL for any valid Delta product symbol
- Reduce-only checkbox
- Open positions panel
- Individual reduce-only Square Off
- Square Off All using reduce-only market orders
- TOTP remains UI-only because API-key trading uses signed API credentials
- No auto-execution from signals

CORRECTED FULL RELEASE
- delta_trading.py INCLUDED
- TOTP UI REMOVED
- Replaced with Delta API / Trading / Telegram status panel
- API key + secret expected only in Render Environment
- Locked robotic single-page UI retained
- Manual BUY/SELL retained
- Positions retained
- Individual Square Off retained
- Square Off All retained
- BTC/ETH/GOLD strategy retained
- 40-token Delta ticker groups retained
