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


STRATEGY V3.1 TRACKER FIX
- Recent Signals panel now uses ONLY /api/signals/history lifecycle events.
- NO_TRADE scans can no longer overwrite Recent Signals.
- Active signal count comes from server ACTIVE_SIGNALS.
- Target/SL detection uses completed 5M candle HIGH/LOW, not close only.
- Conservative same-candle rule: if SL and target both touch, SL is counted first.
- Telegram sends T1/T2/T3 and SL lifecycle updates.
- Duplicate new entry Telegram signals are blocked while an asset is ACTIVE.
- Active dashboard cards remain ACTIVE/T1_HIT/T2_HIT until T3 or SL closes them.
- Lifecycle state is in server memory. A Render redeploy/restart starts a fresh lifecycle session.

V3.2 DELTA TICK STREAM
- One public Delta WebSocket connection: wss://public-socket.india.delta.exchange
- Subscribes to trades for BTCUSD, ETHUSD, PAXGUSD.
- Full strategy STILL runs only on newly closed 5M candles.
- Tick stream updates current rate + active signal TP/SL lifecycle only.
- Browser reads in-memory live cache every 350ms; it does NOT hit Delta every 350ms.
- WebSocket auto reconnects with backoff and protocol ping/pong.
- Existing 40-token table keeps low-load cached REST behavior.
- UI shows WS LIVE / RECONNECTING and TICK LIVE / REST FALLBACK.

V3.3 DATA COLLECTION / BACKTEST FOUNDATION
- Every lifecycle OPEN/T1/T2/T3/SL event is appended to data/signal_events.jsonl.
- Every completed T3 or SL trade is appended to data/closed_trades.csv.
- /api/performance reports trade count, win rate, average R, profit factor,
  T1/T2/T3 hit rates and per-asset results.
- /api/research/trades exposes the collected closed-trade journal.
- backtest.py validates historical OHLCV CSV datasets.
IMPORTANT: Render ephemeral filesystem can be lost on restart/redeploy. For a durable
long-term dataset, use an external persistent database/store before relying on this
journal for months of research.

V3.4 OX ALPHA AI ASSISTANT
Render environment variables:
OPENROUTER_API_KEY=<your OpenRouter key>
AI_MODEL=stealth/ox-alpha
AI_CHAT_ENABLED=true
APP_PUBLIC_URL=https://krypt-bro-signal-engine-v2-py.onrender.com

Security:
- Delta API key/secret are NEVER sent to the AI.
- Telegram bot token is NEVER sent to the AI.
- AI receives sanitized live market, signal, lifecycle, positions summary and performance context only.
- AI order execution permission is hard-coded OFF in this release.
- AI failure does not stop the scanner, WebSocket, Telegram, or trading backend.

UI:
- Bottom-right glowing AI orb.
- Floating chat panel, Malayalam/English.
- Quick questions for BTC / strongest setup / active signal explanation.
