KRYPT BRO V4 REAL FIX + AI FIX

AI ROOT CAUSE FIXED
Previous _ai_context() called:
    eng.dashboard_snapshot()
but backend.signal_engine has no dashboard_snapshot() function.

This build:
- removes dashboard_snapshot dependency completely;
- builds AI signal context from the current engine's ASSETS, ASSET_ENABLED,
  LATEST_STATUS, active_signal_snapshot() and performance_stats();
- prevents Delta positions/IP-whitelist errors from breaking AI chat;
- keeps AI strictly READ ONLY;
- logs AI CHAT REQUEST / SUCCESS / FAILED for easy Render diagnosis;
- preserves Delta live tick parser fix (`sy`), SSE live stream, Telegram,
  token emblems, signal engine, lifecycle and simple trading ON/OFF.

EXPECTED AI TEST
POST /api/ai/chat
Success:
    HTTP 200
Render:
    AI CHAT REQUEST ...
    AI CHAT SUCCESS ...
