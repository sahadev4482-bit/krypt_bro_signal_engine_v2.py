import csv, json, os, threading
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("KRYPT_DATA_DIR", "data"))
EVENTS = DATA_DIR / "signal_events.jsonl"
TRADES = DATA_DIR / "closed_trades.csv"
_lock = threading.RLock()

FIELDS = [
    "signal_id","asset","side","opened_at","closed_at","entry","sl","t1","t2","t3",
    "score","grade","rr","exit_price","exit_event","result_r","t1_hit","t2_hit","t3_hit"
]

def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TRADES.exists():
        with TRADES.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def event(kind, payload):
    _ensure()
    row={"ts":datetime.now(timezone.utc).isoformat(),"event":kind,**payload}
    with _lock, EVENTS.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,default=str,separators=(",",":"))+"\n")

def close_trade(s, exit_event, exit_price, result_r):
    _ensure()
    row={
        "signal_id":s.get("signal_id"),"asset":s.get("asset"),"side":s.get("side"),
        "opened_at":s.get("opened_at"),"closed_at":datetime.now(timezone.utc).isoformat(),
        "entry":s.get("entry"),"sl":s.get("sl"),"t1":s.get("t1"),"t2":s.get("t2"),"t3":s.get("t3"),
        "score":s.get("score"),"grade":s.get("grade"),"rr":s.get("rr"),
        "exit_price":exit_price,"exit_event":exit_event,"result_r":round(float(result_r),4),
        "t1_hit":bool(s.get("t1_hit")),"t2_hit":bool(s.get("t2_hit")),"t3_hit":bool(s.get("t3_hit"))
    }
    with _lock, TRADES.open("a",newline="",encoding="utf-8") as f:
        csv.DictWriter(f,fieldnames=FIELDS).writerow(row)
    event("TRADE_CLOSED",row)

def read_trades(limit=5000):
    _ensure()
    with _lock, TRADES.open("r",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    return rows[-limit:]

def summary():
    rows=read_trades()
    if not rows:
        return {"trades":0,"win_rate":None,"avg_r":None,"profit_factor":None,"total_r":0,
                "t1_rate":None,"t2_rate":None,"t3_rate":None,"by_asset":{}}
    rs=[float(x["result_r"] or 0) for x in rows]
    wins=sum(r>0 for r in rs)
    gp=sum(r for r in rs if r>0); gl=abs(sum(r for r in rs if r<0))
    def rate(k): return round(100*sum(str(x[k]).lower()=="true" for x in rows)/len(rows),1)
    by={}
    for a in sorted(set(x["asset"] for x in rows)):
        ar=[float(x["result_r"] or 0) for x in rows if x["asset"]==a]
        by[a]={"trades":len(ar),"win_rate":round(100*sum(r>0 for r in ar)/len(ar),1),
               "avg_r":round(sum(ar)/len(ar),3),"total_r":round(sum(ar),3)}
    return {"trades":len(rows),"win_rate":round(100*wins/len(rows),1),
            "avg_r":round(sum(rs)/len(rs),3),"profit_factor":None if gl==0 else round(gp/gl,3),
            "total_r":round(sum(rs),3),"t1_rate":rate("t1_hit"),"t2_rate":rate("t2_hit"),
            "t3_rate":rate("t3_hit"),"by_asset":by}
