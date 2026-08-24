KRYPT BRO V4 FULLSTACK

SINGLE DEPLOY
Start command:
python app.py

STRUCTURE
frontend/
  templates/index.html
  static/css/style.css
  static/js/app.js
backend/
  app_core.py
  signal_engine.py
  delta_ws.py
  delta_trading.py
  ai_assistant.py
  analytics_store.py
  backtest.py
app.py  # Render entry shim

RENDER ENVIRONMENT
DELTA_API_KEY=...
DELTA_API_SECRET=...
DELTA_TRADING_ENABLED=false
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
OPENROUTER_API_KEY=...
AI_MODEL=stealth/ox-alpha
AI_CHAT_ENABLED=true
APP_PUBLIC_URL=https://krypt-bro-signal-engine-v2-py.onrender.com

V4 IMPROVEMENTS
- Separate frontend/backend folders while remaining one Render service.
- Left-side robotic Ox Alpha AI dock.
- AI diagnostics: ONLINE / KEY NEEDED.
- AI is read-only and receives sanitized app context only.
- Delta/API/Telegram secrets are not sent to AI.
- Visible BTC/ETH/GOLD tick direction flashes on the cards.
- WS LIVE / reconnect diagnostics.
- Token emblems for primary and other tokens.
- Positions endpoint returns safe empty response instead of noisy 400s when unavailable.
- Simple Trading ON/OFF switch with browser confirmation, default OFF.
- Emergency square-off remains conceptually reduce-only.
- Other-token MASTER + G1/G2/G3/G4 controls.
- Existing 5M strategy scan remains separate from tick updates.
- Existing lifecycle, Telegram and analytics preserved.

IMPORTANT
Trading TOTP is a dashboard safety lock, not Delta Exchange authentication.
Keep DELTA_TRADING_ENABLED=false until manual tests are complete.

V4 SIMPLE TRADING UPDATE
- No TOTP secret required.
- No 30-minute arm timer.
- Trading defaults OFF after every service restart/deploy.
- Turning ON requires an explicit browser confirmation and configured Delta credentials.
- Market data, scanner, Telegram and AI continue independently while Trading is OFF.
