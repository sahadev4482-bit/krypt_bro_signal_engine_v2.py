AI CHAT CLICK FIX

ROOT CAUSE:
frontend/templates/index.html loaded static/js/app.js BEFORE the AI panel HTML.
Therefore:
  document.getElementById('aiPanel')
  document.getElementById('aiSend')
  document.getElementById('aiInput')
  document.getElementById('aiClose')
were null when app.js initialized.

FIX:
Moved the app.js <script> tag to the very end of <body>, after the entire
AI panel markup.

EXPECTED:
- OX ALPHA CHAT button opens panel.
- SEND button has its click handler.
- Enter sends message.
- Close button works.
- Then /api/ai/chat can be tested separately.

Only frontend load order changed. Signal engine / Telegram / Delta logic untouched.
