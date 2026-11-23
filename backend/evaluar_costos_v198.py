"""Analiza detalle V1.9.7 sin alterar decisiones ni datos originales."""
import argparse,csv,json,statistics
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--csv',required=True,help='detalle.csv de V1.9.7')
p.add_argument('--mt5',help='JSON del diagnóstico MT5')
p.add_argument('--symbol',default='EURUSD')
p.add_argument('--spread',type=float,help='Spread hipotético en pips, si no hay diagnóstico')
p.add_argument('--slippage',type=float,default=.1,help='Costo total de slippage en pips, ida y vuelta')
p.add_argument('--commission-usd-per-lot',type=float,default=0,help='Comisión real total ida/vuelta por lote estándar; confirmar con broker')
p.add_argument('--balance',type=float,default=100)
p.add_argument('--risk-pct',type=float,default=.25)
p.add_argument('--min-lot',type=float,help='Anula mínimo observado, solo para escenario')
p.add_argument('--out',default='auditoria_costos_v198.csv')
a=p.parse_args()
if a.slippage<0 or a.commission_usd_per_lot<0 or a.balance<=0 or a.risk_pct<=0:p.error('Parámetros inválidos')
info={}
if a.mt5:
 m=json.loads(Path(a.mt5).read_text(encoding='utf-8'))
 info=m.get('symbols',{}).get(a.symbol,{})
spread=a.spread if a.spread is not None else info.get('spread_pips_summary',{}).get('median')
if spread is None:raise SystemExit('Falta --spread o --mt5 con muestras válidas. No se inventará un spread.')
if spread<0:p.error('Spread inválido')
minlot=a.min_lot if a.min_lot is not None else info.get('volume_min')
contract=info.get('trade_contract_size')
if not minlot or not contract:print('AVISO: lote mínimo y/o contrato no confirmados; viabilidad monetaria pendiente.')
rows=list(csv.DictReader(Path(a.csv).open(encoding='utf-8-sig',newline='')))
results=[]
for r in rows:
 if r['decision'] not in ('BUY','SELL'):continue
 gross=float(r['pips']); entry=float(r['entry']); sl=float(r['sl'])
 slpips=abs(entry-sl)/.0001
 pipusd=contract*.0001*minlot if contract and minlot else None
 commission_pips=(a.commission_usd_per_lot*minlot/pipusd) if pipusd else None
 net=gross-spread-a.slippage-(commission_pips or 0)
 risk_at_min=(slpips+spread+a.slippage+(commission_pips or 0))*pipusd if pipusd else None
 allowed=a.balance*a.risk_pct/100
 feasible=(risk_at_min<=allowed) if risk_at_min is not None else None
 results.append({**r,'sl_distance_pips':round(slpips,3),'spread_pips':spread,'slippage_pips':a.slippage,'commission_pips':round(commission_pips,4) if commission_pips is not None else 'unknown','net_pips_estimate':round(net,4) if commission_pips is not None or a.commission_usd_per_lot==0 else 'unknown','min_lot':minlot or 'unknown','risk_usd_at_min_lot':round(risk_at_min,4) if risk_at_min is not None else 'unknown','risk_cap_usd':allowed,'risk_feasible':feasible if feasible is not None else 'unknown'})
with Path(a.out).open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
summary={'mode':'OFFLINE_NO_ORDERS','symbol':a.symbol,'trades':len(results),'spread_pips_assumed':spread,'slippage_pips_roundtrip_assumed':a.slippage,'commission_usd_per_lot_roundtrip_assumed':a.commission_usd_per_lot,'commission_verified':False,'min_lot':minlot,'contract_size':contract,'gross_pips':round(sum(float(r['pips']) for r in results),4),'net_pips_estimate':round(sum(float(r['net_pips_estimate']) for r in results),4),'risk_cap_usd':allowed,'feasible_count':sum(r['risk_feasible'] is True for r in results),'infeasible_count':sum(r['risk_feasible'] is False for r in results),'unknown_feasibility_count':sum(r['risk_feasible']=='unknown' for r in results),'warning':'Muestras de spread no representan spreads históricos. Comisiones y slippage deben verificarse. Cálculo usa pips y lote mínimo; no modela bid/ask histórico ni ejecución real.'}
Path(a.out).with_suffix('.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
