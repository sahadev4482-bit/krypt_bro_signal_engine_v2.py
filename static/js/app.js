const tokenList=[
  'SOL','XRP','BNB','ADA','DOGE','AVAX','LINK','LTC','DOT','TRX',
  'BCH','UNI','ATOM','NEAR','APT','ARB','OP','SUI','FIL','INJ',
  'ETC','AAVE','MKR','RUNE','SEI','TIA','WIF','PEPE','SHIB','TON',
  'ICP','HBAR','FET','RENDER','ALGO','GRT','JUP','BONK','PYTH','ENA'
];

async function api(path, opts={}) {
  const response = await fetch(path, opts);
  return response.json();
}

function fmt(v){
  return v === null || v === undefined
    ? '—'
    : Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
}

function pivotTable(p){
  if(!p || Object.keys(p).length===0){
    return '<div class="hint" style="padding:0 10px 8px">Waiting for scan...</div>';
  }
  const order=['R5','R4','R3','R2','R1','P','S1','S2','S3','S4','S5'];
  return '<div class="pivot">' +
    order.map(k=>`<div class="row"><span>${k}</span><b>${fmt(p[k])}</b></div>`).join('') +
    '</div>';
}

function renderTokens(){
  document.getElementById('tokenRows').innerHTML = tokenList.map(token=>`
    <tr>
      <td>${token}</td>
      <td class="pending">Waiting</td>
      <td class="pending">—</td>
      <td class="pending">—</td>
      <td><span class="signal-pill pending">PENDING</span></td>
    </tr>
  `).join('');
}

function flashPrice(id){
  const el=document.getElementById(id);
  if(!el) return;
  el.classList.remove('flash');
  void el.offsetWidth;
  el.classList.add('flash');
}

async function refresh(){
  const d = await api('/api/status');

  const scan = d.scanner_enabled ? 'ON' : 'OFF';
  const telegram = d.telegram_enabled ? 'ON' : 'OFF';

  document.getElementById('mScanner').textContent=scan;
  document.getElementById('mTelegram').textContent=telegram;
  document.getElementById('sideScan').textContent=scan;
  document.getElementById('sideTg').textContent=telegram;

  const master=document.getElementById('master');
  master.className=d.scanner_enabled?'btn green':'btn red';

  const tg=document.getElementById('tg');
  tg.className=d.telegram_enabled?'btn green':'btn red';
  tg.textContent=d.telegram_enabled?'TELEGRAM ON':'TELEGRAM OFF';

  let html='';

  for(const [asset,s] of Object.entries(d.assets)){
    const latest=s.latest;
    const status=latest.status;
    const cls=status==='SIGNAL'?'signal':(status==='NO_TRADE'?'no':'waiting');
    const price=fmt(latest.price);

    if(asset==='BTC'){document.getElementById('topBTC').textContent=price;flashPrice('topBTC')}
    if(asset==='ETH'){document.getElementById('topETH').textContent=price;flashPrice('topETH')}
    if(asset==='GOLD'){document.getElementById('topGOLD').textContent=price;flashPrice('topGOLD')}

    html += `
      <article class="card glass">
        <div class="card-head">
          <div class="asset-name">${asset}</div>
          <button class="asset-toggle ${s.enabled?'btn green':'btn red'}" data-asset="${asset}">
            ${s.enabled?'ON':'OFF'}
          </button>
        </div>

        <div class="row"><span>Status</span><b class="status ${cls}">${status}</b></div>
        <div class="row"><span>Side</span><b>${latest.side||'—'}</b></div>
        <div class="row"><span>Score / Grade</span><b>${latest.score??'—'} / ${latest.grade||'—'}</b></div>
        <div class="row"><span>R:R to T2</span><b>${latest.rr?'1 : '+Number(latest.rr).toFixed(2):'—'}</b></div>
        <div class="row"><span>Current / Signal Price</span><b>${price}</b></div>
        <div class="row"><span>SL</span><b>${fmt(latest.stop)}</b></div>
        <div class="row"><span>T1 / T2 / T3</span><b>${fmt(latest.t1)} / ${fmt(latest.t2)} / ${fmt(latest.t3)}</b></div>

        <div class="reason">${latest.reason||'VALID SIGNAL SETUP'}</div>

        <details>
          <summary>Daily Fib Pivot • P / R1-R5 / S1-S5</summary>
          ${pivotTable(latest.daily_fibs)}
        </details>

        <details>
          <summary>5M Fib Pivot • P / R1-R5 / S1-S5</summary>
          ${pivotTable(latest.five_min_fibs)}
        </details>
      </article>
    `;
  }

  const cards=document.getElementById('cards');
  cards.innerHTML=html;

  document.querySelectorAll('[data-asset]').forEach(button=>{
    button.addEventListener('click',async()=>{
      await api('/api/toggle-asset/'+button.dataset.asset,{method:'POST'});
      refresh();
    });
  });
}

document.getElementById('master').addEventListener('click',async()=>{
  await api('/api/toggle-scanner',{method:'POST'});
  refresh();
});

document.getElementById('tg').addEventListener('click',async()=>{
  await api('/api/toggle-telegram',{method:'POST'});
  refresh();
});

document.getElementById('refreshBtn').addEventListener('click',refresh);

document.getElementById('totpSubmit').addEventListener('click',()=>{
  const field=document.getElementById('totp');
  const hint=document.getElementById('totpHint');
  const value=field.value.trim();

  if(!/^[0-9]{6}$/.test(value)){
    hint.textContent='Enter a valid 6-digit TOTP.';
    return;
  }

  hint.textContent='TOTP UI validated. Trading authentication is not connected yet.';
  field.value='';
});

renderTokens();
refresh();
setInterval(refresh,5000);
