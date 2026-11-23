import argparse,csv,json,random,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--csv',required=True);p.add_argument('--out',default='validacion_v20.json');a=p.parse_args()
with open(a.csv,encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
trades=[r for r in rows if r['risk_feasible'].strip().lower()=='true']
trades.sort(key=lambda r:r['time'])
def metrics(rr):
 vals=[float(r['net_pips_estimate']) for r in rr]; gross=[float(r['pips']) for r in rr]
 return {'n':len(rr),'gross_pips':round(sum(gross),3),'net_pips':round(sum(vals),3),'mean_net_pips':round(statistics.mean(vals),4) if vals else None,'wins_net':sum(x>0 for x in vals),'losses_net':sum(x<0 for x in vals)}
base=metrics(trades)
by_dir={d:metrics([r for r in trades if r['decision']==d]) for d in ['BUY','SELL']}
by_outcome={d:metrics([r for r in trades if r['reference_outcome']==d]) for d in sorted(set(r['reference_outcome'] for r in trades))}
# Bootstrap is descriptive, not a valid confidence interval under temporal dependence.
rng=random.Random(20261120); vals=[float(r['net_pips_estimate']) for r in trades]; n=len(vals)
boots=sorted(sum(rng.choices(vals,k=n))/n for _ in range(10000))
report={'mode':'OFFLINE_NO_ORDERS','source':'V1.9.8 CSV','assumptions':'Spread 0.8 pip, slippage 0.2 pip, commission 0 assumed unverified; execution not simulated with historical bid/ask','overall':base,'direction':by_dir,'outcome':by_outcome,'chronological_halves':{'first':metrics(trades[:n//2]),'second':metrics(trades[n//2:])},'cost_sensitivity':{str(x):round(sum(float(r['pips'])-x for r in trades),3) for x in [0.8,1.0,1.1,1.2,1.5]},'break_even_total_cost_pips':round(sum(float(r['pips']) for r in trades)/n,4),'naive_iid_bootstrap_mean_95pct_pips':[round(boots[249],4),round(boots[9749],4)],'warnings':['Bootstrap assumes independent identically distributed trades and is not evidence of independent validation','11 pilot versus 89 new decisions cannot be identified reliably from this CSV alone','No commission, variable spread, slippage or actual execution confirmed','Chronological halves are descriptive, not a held-out test']}
Path(a.out).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(report,indent=2,ensure_ascii=False))
