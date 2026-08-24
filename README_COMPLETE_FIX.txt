KRYPT BRO V4 COMPLETE FIX

FIXED:
1. /api/trading/status -> restored (no more 404)
2. /api/system/diagnostics -> restored (no more 404)
3. /api/live -> always returns full delta_ws.snapshot()
4. Tick UI:
   - keeps SSE /api/live/stream
   - adds REST fallback /api/live if SSE does not deliver within 1.5 seconds
   - BTC/ETH/GOLD boxes should no longer remain WAITING when backend quotes exist
5. AI context dashboard_snapshot bug remains fixed
6. Existing signal engine, Telegram, emblems, robot UI preserved

EXPECTED AFTER DEPLOY:
GET /api/trading/status -> 200
GET /api/system/diagnostics -> 200
GET /api/live -> 200
GET /api/live/stream -> 200
POST /api/ai/chat -> 200 (if OpenRouter provider accepts the request)
