import os
import threading
import time
from flask import Flask, jsonify, render_template_string, request

import signal_engine as eng

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KRYPT BRO</title>
<style>
:root{--sky:#79d7ff;--cyan:#18d7ff;--blue:#0e67d1;--teal:#00d8b4;--green:#21dd8a;--orange:#ffad3d;--red:#ff5f75;--text:#08386f;--muted:#4e75a5;--line:rgba(16,111,196,.20)}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,Arial,sans-serif;color:var(--text);min-height:100vh;background:radial-gradient(circle at 15% 10%,rgba(0,210,255,.34),transparent 30%),radial-gradient(circle at 85% 8%,rgba(0,222,180,.28),transparent 30%),linear-gradient(135deg,#dff7ff 0%,#a9e6ff 35%,#d8f7ff 66%,#bdefff 100%);background-attachment:fixed}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(115deg,transparent 0 42%,rgba(255,255,255,.22) 48%,transparent 55%);animation:lightSweep 16s linear infinite}
@keyframes lightSweep{0%{transform:translateX(-8%)}50%{transform:translateX(8%)}100%{transform:translateX(-8%)}}
@media (prefers-reduced-motion:reduce){body:before,.liveDot,.priceFlash{animation:none!important}}
.shell{max-width:1500px;margin:auto;padding:18px}
.header,.panel,.card,.tokenPanel{background:linear-gradient(145deg,rgba(255,255,255,.78),rgba(226,248,255,.70));border:1px solid var(--line);box-shadow:0 16px 40px rgba(13,107,178,.12),inset 0 1px 0 rgba(255,255,255,.85);backdrop-filter:blur(16px)}
.header{display:grid;grid-template-columns:1.2fr 2fr auto;gap:14px;align-items:center;border-radius:24px;padding:15px 18px}
.brand{display:flex;gap:12px;align-items:center}.logo{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;font-size:28px;background:linear-gradient(145deg,#22dfff,#0f7be7);color:white}
.brand h1{font-size:30px;line-height:1;margin:0;color:#07529c}.brand small{color:var(--muted);font-weight:700}
.metrics{display:grid;grid-template-columns:repeat(5,minmax(90px,1fr));gap:10px}.metric{background:rgba(255,255,255,.58);border:1px solid var(--line);border-radius:15px;padding:10px;text-align:center}.metric span{display:block;font-size:12px;color:var(--muted)}.metric b{display:block;font-size:18px;color:#0868c5;margin-top:3px}
.livePill{display:flex;align-items:center;gap:8px;padding:10px 14px;border-radius:999px;background:rgba(255,255,255,.68);border:1px solid var(--line);font-weight:800}.liveDot{width:10px;height:10px;border-radius:50%;background:#14d67b;box-shadow:0 0 14px #14d67b;animation:pulse 1.8s infinite}@keyframes pulse{50%{transform:scale(1.28);opacity:.65}}
.controls{margin-top:14px;display:grid;grid-template-columns:1.3fr 1fr;gap:14px}.panel,.tokenPanel{border-radius:22px;padding:15px}.panelTitle{font-weight:900;color:#0a5eae;margin-bottom:10px}
.btns{display:flex;flex-wrap:wrap;gap:10px}button{border:none;border-radius:13px;padding:11px 16px;font-weight:900;cursor:pointer;color:white;box-shadow:0 8px 18px rgba(12,106,178,.13)}.btnBlue{background:linear-gradient(135deg,#1599ef,#0b61cf)}.btnGreen{background:linear-gradient(135deg,#22d89a,#08af79)}.btnRed{background:linear-gradient(135deg,#ff7b82,#f14f66)}.btnSoft{background:linear-gradient(135deg,#46b5ff,#2686df)}
.stateRow,.row{display:flex;justify-content:space-between;gap:12px}.stateRow{margin-top:11px;color:var(--muted);font-size:14px}.stateRow b{color:#075faf}
.totpWrap{display:grid;grid-template-columns:1fr auto;gap:10px}.totpWrap input{width:100%;min-width:0;border:1px solid rgba(17,105,180,.25);border-radius:13px;background:rgba(255,255,255,.68);padding:12px 14px;font-size:16px;outline:none;color:#0b4f91}.hint{font-size:12px;color:var(--muted);margin-top:8px}
.assetGrid{margin-top:14px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{border-radius:22px;padding:16px}.cardHead{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px}.assetName{font-size:24px;font-weight:950;color:#064e98}.assetToggle{padding:8px 13px;border-radius:999px;font-size:12px}
.signal{color:#0db676}.no{color:#f29624}.waiting{color:#087cd9}.row{margin:7px 0;font-size:14px}.row span{color:#4d73a2}.row b{color:#073f79;text-align:right}.reason{margin-top:10px;padding:9px 11px;border-radius:12px;background:rgba(255,176,47,.13);color:#b86d00;font-size:13px;font-weight:800}
details{margin-top:9px;border:1px solid rgba(8,111,195,.18);border-radius:12px;background:rgba(255,255,255,.48);overflow:hidden}summary{cursor:pointer;padding:10px 11px;font-weight:900;color:#075da9}.pivotBox{padding:0 11px 8px}
.sectionTitle{margin:18px 2px 9px;font-weight:950;color:#0756a1;font-size:18px}.groupTabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.groupTab{background:linear-gradient(135deg,#5ecbff,#2a8de3);padding:8px 12px;border-radius:999px;font-size:12px}.tokenGrid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.token{padding:11px;border-radius:14px;background:rgba(255,255,255,.62);border:1px solid rgba(11,110,191,.16)}.sym{font-weight:950;color:#0759a6}.price{font-size:15px;font-weight:900;color:#084980;margin-top:5px}.meta{font-size:11px;color:var(--muted);margin-top:4px}
.footerStrip{margin-top:14px;padding:11px 14px;border-radius:16px;background:linear-gradient(90deg,rgba(255,255,255,.65),rgba(218,247,255,.70));border:1px solid var(--line);display:flex;gap:18px;flex-wrap:wrap;color:#316590;font-size:13px;font-weight:700}
.priceFlash{animation:tickGlow .55s ease}@keyframes tickGlow{50%{text-shadow:0 0 16px rgba(0,167,255,.65)}}
@media(max-width:1100px){.header{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(3,1fr)}.controls{grid-template-columns:1fr}.assetGrid{grid-template-columns:1fr}.tokenGrid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.shell{padding:10px}.metrics{grid-template-columns:repeat(2,1fr)}.tokenGrid{grid-template-columns:1fr}.brand h1{font-size:24px}.totpWrap{grid-template-columns:1fr}.btns button{flex:1 1 45%}}
</style>
</head>
<body>
<div class="shell">
<header class="header">
<div class="brand"><div class="logo">⚡</div><div><h1>KRYPT BRO</h1><small>Delta Signal Terminal • Min R:R 1:1.8</small></div></div>
<div class="metrics">
<div class="metric"><span>Scanner</span><b id="mScanner">ON</b></div>
<div class="metric"><span>Telegram</span><b id="mTelegram">ON</b></div>
<div class="metric"><span>Markets</span><b>BTC / ETH / GOLD</b></div>
<div class="metric"><span>Engine</span><b>5M Close</b></div>
<div class="metric"><span>Data</span><b>DELTA</b></div>
</div>
<div class="livePill"><i class="liveDot"></i> LIVE</div>
</header>

<section class="controls">
<div class="panel">
<div class="panelTitle">SCAN CONTROLS</div>
<div class="btns"><button id="master" class="btnGreen" type="button">MASTER SCAN</button><button id="tg" class="btnGreen" type="button">TELEGRAM</button><button class="btnSoft" id="refreshBtn" type="button">REFRESH</button></div>
<div class="stateRow"><span>Scanner status</span><b id="scannerState">...</b></div><div class="stateRow"><span>Telegram status</span><b id="telegramState">...</b></div>
</div>
<div class="panel">
<div class="panelTitle">TRADING LOGIN • TOTP</div>
<div class="totpWrap"><input id="totp" inputmode="numeric" maxlength="6" placeholder="Enter 6-digit TOTP only when needed"><button class="btnBlue" type="button" id="totpSubmit">SUBMIT</button></div>
<div class="hint" id="totpHint">UI placeholder only. Trading login API will be connected later.</div>
</div>
</section>

<div class="sectionTitle">PRIMARY SIGNALS</div>
<section class="assetGrid" id="cards"></section>

<div class="sectionTitle">OTHER TOKENS • 4 GROUPS × 10</div>
<section class="tokenPanel">
<div class="groupTabs"><button class="groupTab" type="button">GROUP 1</button><button class="groupTab" type="button">GROUP 2</button><button class="groupTab" type="button">GROUP 3</button><button class="groupTab" type="button">GROUP 4</button></div>
<div class="tokenGrid" id="tokenGrid"></div>
</section>

<div class="footerStrip"><span>Data source: Delta Exchange</span><span>No live chart • lightweight terminal</span><span>Signal Engine: Volume + Breakout/Retest + Fib + MTF</span><span>Daily + 5M Fib Pivot: P / R1-R5 / S1-S5</span></div>
</div>

<script>
const tokens=['SOL','XRP','BNB','ADA','DOGE','AVAX','LINK','LTC','DOT','TRX','BCH','UNI','ATOM','NEAR','APT','ARB','OP','SUI','FIL','INJ','ETC','AAVE','MKR','RUNE','SEI','TIA','WIF','PEPE','SHIB','TON','ICP','HBAR','FET','RENDER','ALGO','GRT','JUP','BONK','PYTH','ENA'];
async function api(path,opts={}){const r=await fetch(path,opts);return await r.json();}
function fmt(v){return v===null||v===undefined?'-':Number(v).toLocaleString(undefined,{maximumFractionDigits:2});}
function pivotTable(p){if(!p||Object.keys(p).length===0)return '<div class="hint">Waiting for next completed scan...</div>';const order=['R5','R4','R3','R2','R1','P','S1','S2','S3','S4','S5'];return '<div class="pivotBox">'+order.map(k=>`<div class="row"><span>${k}</span><b>${fmt(p[k])}</b></div>`).join('')+'</div>';}
function renderTokens(){document.getElementById('tokenGrid').innerHTML=tokens.map((t,i)=>`<div class="token"><div class="sym">${t}</div><div class="price">Waiting…</div><div class="meta">Group ${Math.floor(i/10)+1} • scanner pending</div></div>`).join('');}
async function refresh(){
const d=await api('/api/status');
document.getElementById('scannerState').textContent=d.scanner_enabled?'ON':'OFF';
document.getElementById('telegramState').textContent=d.telegram_enabled?'ON':'OFF';
document.getElementById('mScanner').textContent=d.scanner_enabled?'ON':'OFF';
document.getElementById('mTelegram').textContent=d.telegram_enabled?'ON':'OFF';
document.getElementById('master').className=d.scanner_enabled?'btnGreen':'btnRed';
document.getElementById('tg').className=d.telegram_enabled?'btnGreen':'btnRed';
let html='';
for(const [asset,s] of Object.entries(d.assets)){
const st=s.latest.status;const cls=st==='SIGNAL'?'signal':(st==='NO_TRADE'?'no':'waiting');
html+=`<article class="card"><div class="cardHead"><div class="assetName">${asset}</div><button type="button" class="assetToggle ${s.enabled?'btnGreen':'btnRed'}" data-asset="${asset}">${s.enabled?'ON':'OFF'}</button></div><div class="row"><span>Status</span><b class="${cls}">${st}</b></div><div class="row"><span>Side</span><b>${s.latest.side||'-'}</b></div><div class="row"><span>Score / Grade</span><b>${s.latest.score??'-'} / ${s.latest.grade||'-'}</b></div><div class="row"><span>R:R to T2</span><b>${s.latest.rr?'1:'+Number(s.latest.rr).toFixed(2):'-'}</b></div><div class="row"><span>Current / Signal Price</span><b class="priceFlash">${fmt(s.latest.price)}</b></div><div class="row"><span>SL</span><b>${fmt(s.latest.stop)}</b></div><div class="row"><span>T1 / T2 / T3</span><b>${fmt(s.latest.t1)} / ${fmt(s.latest.t2)} / ${fmt(s.latest.t3)}</b></div><div class="reason">${s.latest.reason||'Valid signal setup'}</div><details><summary>Daily Fib Pivot • P / R1-R5 / S1-S5</summary>${pivotTable(s.latest.daily_fibs)}</details><details><summary>5M Fib Pivot • P / R1-R5 / S1-S5</summary>${pivotTable(s.latest.five_min_fibs)}</details></article>`;
}
document.getElementById('cards').innerHTML=html;
document.querySelectorAll('[data-asset]').forEach(btn=>btn.addEventListener('click',async()=>{await api('/api/toggle-asset/'+btn.dataset.asset,{method:'POST'});refresh();}));
}
document.getElementById('master').addEventListener('click',async()=>{await api('/api/toggle-scanner',{method:'POST'});refresh();});
document.getElementById('tg').addEventListener('click',async()=>{await api('/api/toggle-telegram',{method:'POST'});refresh();});
document.getElementById('refreshBtn').addEventListener('click',refresh);
document.getElementById('totpSubmit').addEventListener('click',()=>{const v=document.getElementById('totp').value.trim();const hint=document.getElementById('totpHint');if(!/^[0-9]{6}$/.test(v)){hint.textContent='Enter a valid 6-digit TOTP.';return;}hint.textContent='TOTP UI ready. Trading login API is not connected yet.';document.getElementById('totp').value='';});
renderTokens();refresh();setInterval(refresh,5000);
</script>
</body>
</html>
"""

@app.get("/")
def home():
    return render_template_string(HTML)

@app.get("/health")
def health():
    return "KRYPT BRO Dashboard: RUNNING", 200

@app.get("/api/status")
def status():
    return jsonify({
        "scanner_enabled": eng.SCANNER_ENABLED,
        "telegram_enabled": eng.TELEGRAM_ENABLED,
        "min_rr": eng.MIN_RR,
        "assets": {
            a: {
                "enabled": eng.ASSET_ENABLED[a],
                "latest": eng.LATEST_STATUS[a]
            } for a in eng.ASSETS
        }
    })

@app.post("/api/toggle-scanner")
def toggle_scanner():
    eng.SCANNER_ENABLED = not eng.SCANNER_ENABLED
    return jsonify({"scanner_enabled": eng.SCANNER_ENABLED})

@app.post("/api/toggle-telegram")
def toggle_telegram():
    eng.TELEGRAM_ENABLED = not eng.TELEGRAM_ENABLED
    return jsonify({"telegram_enabled": eng.TELEGRAM_ENABLED})

@app.post("/api/toggle-asset/<asset>")
def toggle_asset(asset):
    asset = asset.upper()
    if asset not in eng.ASSET_ENABLED:
        return jsonify({"error": "Unknown asset"}), 404
    eng.ASSET_ENABLED[asset] = not eng.ASSET_ENABLED[asset]
    return jsonify({"asset": asset, "enabled": eng.ASSET_ENABLED[asset]})

def scanner_loop():
    eng.logger.info("Dashboard scanner thread started")
    while True:
        try:
            eng.scan_once()
        except Exception:
            eng.logger.exception("Dashboard scanner loop error")
        time.sleep(eng.SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=eng.keep_alive_ping, daemon=True).start()
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)
