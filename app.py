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
body{font-family:Arial,sans-serif;background:#0b1220;color:#e8f0ff;margin:0;padding:18px}
.wrap{max-width:980px;margin:auto}
.top{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between}
h1{margin:0 0 6px}
.panel,.card{background:#121c2f;border:1px solid #263654;border-radius:16px;padding:16px;box-shadow:0 8px 25px #0004}
.controls{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
button{border:0;border-radius:10px;padding:11px 16px;font-weight:700;cursor:pointer}
.on{background:#18c37e;color:#03140d}.off{background:#ff5d68;color:white}.neutral{background:#2d4168;color:white}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin-top:14px}
.row{display:flex;justify-content:space-between;gap:10px;margin:8px 0}
.muted{color:#9db0cf}.signal{color:#45e59a}.no{color:#ffbd66}.waiting{color:#8db4ff}
.badge{padding:4px 9px;border-radius:999px;background:#223456;font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>⚡ KRYPT BRO</h1>
      <div class="muted">Delta India • Volume + Breakout/Retest • Min R:R 1:1.8</div>
    </div>
    <span class="badge">SIGNAL FIRST</span>
  </div>

  <div class="panel" style="margin-top:16px">
    <div class="controls">
      <button id="master" class="neutral" onclick="toggleMaster()">MASTER SCAN</button>
      <button id="tg" class="neutral" onclick="toggleTelegram()">TELEGRAM</button>
      <button class="neutral" onclick="refresh()">REFRESH</button>
    </div>
    <div class="row"><span>Scanner</span><b id="scannerState">...</b></div>
    <div class="row"><span>Telegram</span><b id="telegramState">...</b></div>
  </div>

  <div class="grid" id="cards"></div>
</div>

<script>
async function api(path, opts={}){const r=await fetch(path,opts);return await r.json();}
function fmt(v){return v===null||v===undefined ? "-" : Number(v).toLocaleString(undefined,{maximumFractionDigits:2});}
function pivotTable(p){
  if(!p || Object.keys(p).length===0) return '<div class="muted" style="margin-top:8px">Waiting for scan...</div>';
  const order=['R5','R4','R3','R2','R1','P','S1','S2','S3','S4','S5'];
  return '<div style="margin-top:8px">'+order.map(k=>`<div class="row"><span>${k}</span><b>${fmt(p[k])}</b></div>`).join('')+'</div>';
}
async function refresh(){
  const d=await api('/api/status');
  document.getElementById('scannerState').textContent=d.scanner_enabled?'ON':'OFF';
  document.getElementById('telegramState').textContent=d.telegram_enabled?'ON':'OFF';
  document.getElementById('master').className=d.scanner_enabled?'on':'off';
  document.getElementById('tg').className=d.telegram_enabled?'on':'off';

  let html='';
  for(const [asset,s] of Object.entries(d.assets)){
    const st=s.latest.status;
    const cls=st==='SIGNAL'?'signal':(st==='NO_TRADE'?'no':'waiting');
    html+=`
    <div class="card">
      <div class="row"><h2 style="margin:0">${asset}</h2>
      <button class="${s.enabled?'on':'off'}" onclick="toggleAsset('${asset}')">${s.enabled?'ON':'OFF'}</button></div>
      <div class="row"><span>Status</span><b class="${cls}">${st}</b></div>
      <div class="row"><span>Side</span><b>${s.latest.side||'-'}</b></div>
      <div class="row"><span>Score / Grade</span><b>${s.latest.score??'-'} / ${s.latest.grade||'-'}</b></div>
      <div class="row"><span>R:R</span><b>${s.latest.rr ? '1:'+Number(s.latest.rr).toFixed(2) : '-'}</b></div>
      <div class="row"><span>Price</span><b>${fmt(s.latest.price)}</b></div>
      <div class="row"><span>SL</span><b>${fmt(s.latest.stop)}</b></div>
      <div class="row"><span>T1 / T2 / T3</span><b>${fmt(s.latest.t1)} / ${fmt(s.latest.t2)} / ${fmt(s.latest.t3)}</b></div>
      <div class="muted" style="margin-top:10px">${s.latest.reason||''}</div>
      <details style="margin-top:14px">
        <summary><b>Daily Fib Pivot • P / R1-R5 / S1-S5</b></summary>
        ${pivotTable(s.latest.daily_fibs)}
      </details>
      <details style="margin-top:10px">
        <summary><b>5M Fib Pivot • P / R1-R5 / S1-S5</b></summary>
        ${pivotTable(s.latest.five_min_fibs)}
      </details>
    </div>`;
  }
  document.getElementById('cards').innerHTML=html;
}
async function toggleMaster(){await api('/api/toggle-scanner',{method:'POST'});refresh();}
async function toggleTelegram(){await api('/api/toggle-telegram',{method:'POST'});refresh();}
async function toggleAsset(a){await api('/api/toggle-asset/'+a,{method:'POST'});refresh();}
refresh(); setInterval(refresh,5000);
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
