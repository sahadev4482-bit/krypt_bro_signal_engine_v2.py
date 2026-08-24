"""
KRYPT BRO research/backtest harness.

Input CSV columns:
timestamp,open,high,low,close,volume

This harness is intentionally separated from live execution. It is for historical
research only. Strategy parity must be validated whenever signal_engine logic changes.
"""
import argparse, json
import pandas as pd

def load_csv(path):
    df=pd.read_csv(path)
    required={"timestamp","open","high","low","close","volume"}
    missing=required-set(df.columns)
    if missing: raise SystemExit(f"Missing columns: {sorted(missing)}")
    df["timestamp"]=pd.to_datetime(df["timestamp"],utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)

def basic_report(df):
    return {
        "rows":len(df),
        "from":str(df.timestamp.iloc[0]) if len(df) else None,
        "to":str(df.timestamp.iloc[-1]) if len(df) else None,
        "note":"Dataset validated. Full walk-forward strategy replay is the next research stage; do not infer profitability from data collection alone."
    }

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("csv")
    a=p.parse_args()
    print(json.dumps(basic_report(load_csv(a.csv)),indent=2))
