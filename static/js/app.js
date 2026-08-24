const TOKENS=[
 ['SOL','G1'],['XRP','G1'],['BNB','G1'],['ADA','G1'],['DOGE','G1'],['AVAX','G1'],['LINK','G1'],['LTC','G1'],['DOT','G1'],['TRX','G1'],
 ['BCH','G2'],['UNI','G2'],['ATOM','G2'],['NEAR','G2'],['APT','G2'],['ARB','G2'],['OP','G2'],['SUI','G2'],['FIL','G2'],['INJ','G2'],
 ['ETC','G3'],['AAVE','G3'],['MKR','G3'],['RUNE','G3'],['SEI','G3'],['TIA','G3'],['WIF','G3'],['PEPE','G3'],['SHIB','G3'],['TON','G3'],
 ['ICP','G4'],['HBAR','G4'],['FET','G4'],['RENDER','G4'],['ALGO','G4'],['GRT','G4'],['JUP','G4'],['BONK','G4'],['PYTH','G4'],['ENA','G4']
];

let currentGroup=1;
let uiPaused=false;
let recent=[];

async function api(path,opts={}){const r=await fetch(path,opts);return r.json()}
function fmt(v){return v===null||v===undefined?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:2})}

function assetIcon(asset){
  if(asset==='BTC') return '<div class="asset-icon btc">₿</div>';
  if(asset==='ETH') return '<div class="asset-icon eth">◆</div>';
  if(asset==='GOLD') return '<div class="asset-icon gold">Au</div>';
  return '<div class="asset-icon">'+asset.slice(0,1)+'</div>';
}

function pivotTable(p){
  if(!p||Object.keys(p).length===0)return '<div style="padding:0 9px 6px;color:#8fcce4;font-size:10px">Waiting for scan...</div>';
  const order=['R5','R4','R3','R2','R1','P','S1','S2','S3','S4','S5'];
  return '<div class="pivot">'+order.map(k=>`<div class="row"><span>${k}</span><b>${fmt(p[k])}</b></div>`).join('')+'</div>'
}

function tokenEmblem(sym){
  const meme={DOGE:'🐕',SHIB:'🐶',PEPE:'🐸',WIF:'🐕',BONK:'🐕'};
  const core={BTC:'₿',ETH:'◆',SOL:'S',XRP:'X',BNB:'B',ADA:'A',GOLD:'Au'};
  return `<span class="token-emblem ${meme[sym]?'meme':''}">${meme[sym]||core[sym]||sym.slice(0,1)}</span>`;
}

function tokenStatus(move){
  if(move===null || move===undefined) return {label:'NO DATA', cls:'pending', score:'—'};
  const abs=Math.abs(move);
  let score=Math.min(99, Math.round(55 + abs * 8));
  if(abs < 0.35) return {label:'QUIET', cls:'pending', score};
  if(move >= 0.35) return {label:'UP MOVE', cls:'side-long', score};
  return {label:'DOWN MOVE', cls:'side-short', score};
}

async function renderTokenGroup(){
  try{
    const payload=await api('/api/tokens');
    const groupTokens=payload.tokens.filter(t=>t.group===currentGroup);

    tokenRows.innerHTML=groupTokens.map(t=>{
      const status=tokenStatus(t.move_pct);
      const move=t.move_pct===null||t.move_pct===undefined
        ? '—'
        : `${t.move_pct>=0?'+':''}${Number(t.move_pct).toFixed(2)}%`;

      return `<tr>
        <td><span class="token-cell">${tokenEmblem(t.symbol)}<b>${t.symbol}</b></span></td>
        <td>${t.rate===null||t.rate===undefined?'—':fmt(t.rate)}</td>
        <td class="${t.move_pct>0?'side-long':t.move_pct<0?'side-short':'pending'}">${move}</td>
        <td>${status.score}</td>
        <td><span class="signal-pill ${status.cls}">${t.available?status.label:'UNAVAILABLE'}</span></td>
      </tr>`;
    }).join('');
  }catch(err){
    tokenRows.innerHTML='<tr><td colspan="5" class="pending">Token feed temporarily unavailable</td></tr>';
  }
}
function renderTicker(data){
  const parts=[];
  for(const [asset,s] of Object.entries(data.assets)){
    parts.push(`<span class="tick-item">${asset} <b>${fmt(s.latest.price)}</b> <i>● LIVE</i></span>`);
  }
  ['SOL','XRP','BNB','ADA','DOGE','AVAX'].forEach(t=>parts.push(`<span class="tick-item">${t} <b>Waiting</b></span>`));
  tickerTrack.innerHTML=parts.join('');
}

function addRecent(asset,latest){
  const key=`${asset}-${latest.status}-${latest.score}-${latest.updated_at}`;
  if(recent.some(x=>x.key===key))return;
  recent.unshift({key,asset,side:latest.side||'—',status:latest.status,score:latest.score??'—'});
  recent=recent.slice(0,5);
  recentSignals.innerHTML=recent.map(x=>`
    <div class="recent-item">
      <span>${x.asset}</span>
      <b class="${x.side==='LONG'?'side-long':x.side==='SHORT'?'side-short':''}">${x.side}</b>
      <span class="status-text">${x.status}</span>
      <b>${x.score}</b>
    </div>`).join('');
}

async function refresh(){
  if(uiPaused)return;
  const d=await api('/api/status');
  const scan=d.scanner_enabled?'ON':'OFF';
  const tele=d.telegram_enabled?'ON':'OFF';
  sideScan.textContent=scan;sideTg.textContent=tele;scannerMetric.textContent=scan;telegramMetric.textContent=tele;
  master.className=d.scanner_enabled?'btn btn-blue':'btn btn-red';
  tg.className=d.telegram_enabled?'btn btn-green':'btn btn-red';
  tg.textContent=d.telegram_enabled?'TELEGRAM ON':'TELEGRAM OFF';
  const tgState=document.getElementById('deltaTelegramState');
  if(tgState){
    tgState.textContent=d.telegram_enabled?'ON':'OFF';
    tgState.className=d.telegram_enabled?'ok':'';
  }

  let html='',active=0,high=0,quality=0,count=0;
  for(const [asset,s] of Object.entries(d.assets)){
    const l=s.latest;const st=l.status;const cls=st==='SIGNAL'?'signal':st==='NO_TRADE'?'no':'waiting';
    if(st==='SIGNAL')active++;
    if(l.grade==='A+'||l.grade==='A')high++;
    if(typeof l.score==='number'){quality+=l.score;count++}
    if(asset==='BTC')topBTC.textContent=fmt(l.price);
    if(asset==='ETH')topETH.textContent=fmt(l.price);
    if(asset==='GOLD')topGOLD.textContent=fmt(l.price);

    html+=`<article class="card glass hud-edge">
      <div class="card-head">
        <div class="asset-heading">${assetIcon(asset)}<div class="asset-title-wrap"><div class="asset-name">${asset} / USD</div><div class="asset-sub">DELTA LIVE • SIGNAL ENGINE</div></div></div>
        <button class="asset-toggle ${s.enabled?'btn btn-green':'btn btn-red'}" data-asset="${asset}">${s.enabled?'ON':'OFF'}</button>
      </div>
      <div class="row"><span>Status</span><b class="status ${cls}">${st}</b></div>
      <div class="row"><span>Side</span><b>${l.side||'—'}</b></div>
      <div class="row"><span>Score / Grade</span><b>${l.score??'—'} / ${l.grade||'—'}</b></div>
      <div class="row"><span>R:R (to T2)</span><b>${l.rr?'1 : '+Number(l.rr).toFixed(2):'—'}</b></div>
      <div class="row"><span>Live Price</span><b class="live-price" data-live-price="${asset}">${fmt(l.price)}</b></div>
      <div class="row"><span>SL</span><b>${fmt(l.stop)}</b></div>
      <div class="row"><span>T1 / T2 / T3</span><b>${fmt(l.t1)} / ${fmt(l.t2)} / ${fmt(l.t3)}</b></div>
      <div class="reason">${l.reason||'VALID SIGNAL SETUP'}</div>
      <details><summary>Daily Fib Pivot • P / R1-R5 / S1-S5</summary>${pivotTable(l.daily_fibs)}</details>
      <details><summary>5M Fib Pivot • P / R1-R5 / S1-S5</summary>${pivotTable(l.five_min_fibs)}</details>
    </article>`;
  }
  cards.innerHTML=html;
  const serverActive = d.active_signals
    ? Object.values(d.active_signals).filter(Boolean).length
    : active;
  activeSignals.textContent=serverActive;
  highGrade.textContent=high;
  qualityScore.textContent=count?Math.round(quality/count):'—';
  if(d.performance && d.performance.win_rate!==null){ qualityScore.textContent=Math.round(d.performance.win_rate); }

  document.querySelectorAll('[data-asset]').forEach(btn=>btn.addEventListener('click',async()=>{
    await api('/api/toggle-asset/'+btn.dataset.asset,{method:'POST'});refresh()
  }));

  renderTicker(d);
  renderTokenGroup();
}

document.querySelectorAll('.group').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('.group').forEach(x=>x.classList.remove('active'));
  btn.classList.add('active');currentGroup=Number(btn.dataset.group);renderTokenGroup()
}));

master.addEventListener('click',async()=>{await api('/api/toggle-scanner',{method:'POST'});refresh()});
tg.addEventListener('click',async()=>{await api('/api/toggle-telegram',{method:'POST'});refresh()});
refreshBtn.addEventListener('click',refresh);
pauseBtn.addEventListener('click',()=>{uiPaused=!uiPaused;pauseBtn.textContent=uiPaused?'▶ RESUME UI':'Ⅱ PAUSE UI'});
async function loadSignalHistory(){
  try{
    const d=await api('/api/signals/history?limit=20');
    const allowed=new Set(['OPEN','T1_HIT','T2_HIT','T3_HIT','SL_HIT','CLOSE']);
    const rows=(d.signals||[]).filter(x=>allowed.has(x.event)).slice(0,8);

    recentSignals.innerHTML=rows.length
      ? rows.map(x=>{
          let label=x.event;
          if(x.event==='OPEN') label='ACTIVE';
          if(x.event==='CLOSE') label=x.status||'CLOSED';
          return `<div class="recent-item">
            <span>${tokenEmblem(x.asset)} ${x.asset}</span>
            <b class="${x.side==='LONG'?'side-long':'side-short'}">${x.side||'—'}</b>
            <span class="status-text">${label}</span>
            <b>${x.score??'—'}</b>
          </div>`;
        }).join('')
      : '<div class="pending">No lifecycle signal recorded since this server started</div>';
  }catch(e){
    recentSignals.innerHTML='<div class="pending">Signal history API unavailable</div>';
  }
}
renderTokenGroup();
loadSignalHistory();
refresh();
setInterval(()=>{refresh();loadSignalHistory();},5000);


async function loadTradingStatus(){
  try{
    const s=await api('/api/trading/status');

    tradeStatus.textContent=s.trading_enabled?'ARMED':(s.credentials_configured?'DISARMED':'NO API');
    tradeStatus.style.color=s.trading_enabled?'#32ef8f':'#ffd75a';

    const apiState=document.getElementById('deltaApiState');
    const tradingState=document.getElementById('deltaTradingState');
    const telegramState=document.getElementById('deltaTelegramState');

    if(apiState){
      apiState.textContent=s.credentials_configured?'CONNECTED':'NO API';
      apiState.className=s.credentials_configured?'ok':'bad';
    }

    if(tradingState){
      tradingState.textContent=s.trading_enabled?'ARMED':'DISARMED';
      tradingState.className=s.trading_enabled?'ok':'';
    }

    if(telegramState){
      telegramState.textContent=document.getElementById('sideTg')?.textContent || 'ON';
      telegramState.className='ok';
    }

    tradeMessage.textContent=s.credentials_configured
      ? (s.trading_enabled
          ? 'Live trading enabled. Manual orders are LIVE.'
          : 'Credentials found. Trading is safely DISARMED.')
      : 'Set DELTA_API_KEY and DELTA_API_SECRET in Render Environment.';
  }catch(e){
    tradeStatus.textContent='ERROR';
    const apiState=document.getElementById('deltaApiState');
    if(apiState){apiState.textContent='ERROR';apiState.className='bad';}
  }
}

function positionPnl(p){
  const vals=[p.unrealized_pnl,p.unrealised_pnl,p.realized_pnl];
  for(const v of vals){
    const n=Number(v);
    if(Number.isFinite(n)) return n;
  }
  return null;
}

async function loadPositions(){
  positionsRows.innerHTML='<tr><td colspan="5" class="pending">Loading positions...</td></tr>';
  try{
    const d=await api('/api/positions');
    if(!d.success || !d.positions || d.positions.length===0){
      positionsRows.innerHTML='<tr><td colspan="5" class="pending">No open positions / API unavailable</td></tr>';
      return;
    }

    positionsRows.innerHTML=d.positions
      .filter(p=>Number(p.size)!==0)
      .map(p=>{
        const pnl=positionPnl(p);
        return `<tr>
          <td>${p.product_symbol||p.product_id}</td>
          <td>${p.size}</td>
          <td>${p.entry_price||'—'}</td>
          <td style="color:${pnl===null?'#9edcf3':pnl>=0?'#32ef8f':'#ff6478'}">${pnl===null?'—':pnl.toFixed(2)}</td>
          <td><button class="square-btn" data-square='${JSON.stringify({
            product_id:p.product_id,
            product_symbol:p.product_symbol,
            size:p.size
          }).replace(/'/g,"&#39;")}'>SQUARE OFF</button></td>
        </tr>`;
      }).join('') || '<tr><td colspan="5" class="pending">No open positions</td></tr>';

    document.querySelectorAll('[data-square]').forEach(btn=>{
      btn.addEventListener('click',async()=>{
        if(!confirm('Square off this position with a reduce-only market order?')) return;
        const payload=JSON.parse(btn.dataset.square);
        const r=await fetch('/api/square-off',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload)
        });
        const d=await r.json();
        tradeMessage.textContent=d.success?'Square-off order sent.':d.error;
        loadPositions();
      });
    });
  }catch(e){
    positionsRows.innerHTML='<tr><td colspan="5" class="pending">Could not load positions</td></tr>';
  }
}

async function sendTrade(side){
  const product_symbol=tradeSymbol.value.trim().toUpperCase();
  const size=Number(tradeSize.value);
  const reduce_only=reduceOnly.checked;

  if(!product_symbol || !Number.isInteger(size) || size<=0){
    tradeMessage.textContent='Enter product symbol and a positive integer size.';
    return;
  }

  if(!confirm(`${side.toUpperCase()} ${size} ${product_symbol} at MARKET?`)) return;

  tradeMessage.textContent='Sending order...';

  const r=await fetch('/api/order',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({product_symbol,size,side,reduce_only})
  });
  const d=await r.json();
  tradeMessage.textContent=d.success?'Order accepted by Delta.':d.error;
  if(d.success) loadPositions();
}

buyBtn.addEventListener('click',()=>sendTrade('buy'));
sellBtn.addEventListener('click',()=>sendTrade('sell'));
reloadPositionsBtn.addEventListener('click',loadPositions);
squareAllBtn.addEventListener('click',async()=>{
  if(!confirm('SQUARE OFF ALL open positions using reduce-only market orders?')) return;
  tradeMessage.textContent='Closing all positions...';
  const r=await fetch('/api/square-off-all',{method:'POST'});
  const d=await r.json();
  tradeMessage.textContent=d.success?'Square-off-all requests completed.':d.error;
  loadPositions();
});

loadTradingStatus();
loadPositions();
setInterval(loadPositions,15000);


// ===== OX ALPHA / KRYPT BRO READ-ONLY AI CHAT =====
const aiOrb=document.getElementById('aiOrb');
const aiPanel=document.getElementById('aiPanel');
const aiClose=document.getElementById('aiClose');
const aiInput=document.getElementById('aiInput');
const aiSend=document.getElementById('aiSend');
const aiMessages=document.getElementById('aiMessages');
const aiStatusLine=document.getElementById('aiStatusLine');
const aiMode=document.getElementById('aiMode');
let aiHistory=[];

function aiAdd(role,text,extra=''){
  const el=document.createElement('div');
  el.className=`ai-msg ${role} ${extra}`.trim();
  el.textContent=text;
  aiMessages.appendChild(el);
  aiMessages.scrollTop=aiMessages.scrollHeight;
}

async function aiCheckStatus(){
  try{
    const s=await api('/api/ai/status');
    if(aiMode) aiMode.textContent=s.configured?`${s.model} • READ-ONLY`:'API KEY NOT CONFIGURED';
    if(aiStatusLine) aiStatusLine.textContent=s.configured
      ? 'Live app context: ON • AI order execution: OFF'
      : 'Set OPENROUTER_API_KEY in Render • AI order execution: OFF';
  }catch(e){}
}

async function aiAsk(prefill=null){
  const message=(prefill!==null?prefill:aiInput.value).trim();
  if(!message) return;
  if(prefill===null) aiInput.value='';

  aiAdd('user',message);
  aiHistory.push({role:'user',content:message});
  aiSend.disabled=true;
  aiStatusLine.textContent='Reading current KRYPT BRO context and asking AI...';

  try{
    const r=await fetch('/api/ai/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message,history:aiHistory.slice(-6)})
    });
    const d=await r.json();
    if(!d.success) throw new Error(d.error||'AI request failed');
    aiAdd('assistant',d.answer);
    aiHistory.push({role:'assistant',content:d.answer});
    aiStatusLine.textContent=`${d.model} • READ-ONLY • order execution OFF`;
  }catch(e){
    aiAdd('error',String(e.message||e));
    aiStatusLine.textContent='AI unavailable • live signal engine is unaffected';
  }finally{
    aiSend.disabled=false;
  }
}

if(aiOrb) aiOrb.addEventListener('click',()=>{
  aiPanel.classList.add('open');aiPanel.setAttribute('aria-hidden','false');aiCheckStatus();
});
if(aiClose) aiClose.addEventListener('click',()=>{
  aiPanel.classList.remove('open');aiPanel.setAttribute('aria-hidden','true');
});
if(aiSend) aiSend.addEventListener('click',()=>aiAsk());
if(aiInput) aiInput.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();aiAsk();}
});
document.querySelectorAll('[data-ai-q]').forEach(b=>b.addEventListener('click',()=>aiAsk(b.dataset.aiQ)));
aiCheckStatus();
