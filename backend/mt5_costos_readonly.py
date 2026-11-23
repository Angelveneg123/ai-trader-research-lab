"""Diagnóstico SOLO LECTURA de símbolos y costos de MT5. Nunca envía órdenes."""
import json, statistics, time, argparse
from datetime import datetime, timezone
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--symbols', nargs='+', default=['EURUSD','EURUSDmicro'])
p.add_argument('--samples',type=int,default=20)
p.add_argument('--interval',type=float,default=1.0)
p.add_argument('--out',default='mt5_costos_v198.json')
a=p.parse_args()
if not (1<=a.samples<=120 and .1<=a.interval<=60):p.error('Muestras 1..120 e intervalo 0.1..60')
try:import MetaTrader5 as mt5
except ImportError:raise SystemExit('Instalá MetaTrader5 en el entorno de Python que usa MT5.')
if not mt5.initialize():raise SystemExit(f'MT5 no conecta: {mt5.last_error()}')
try:
 account=mt5.account_info()
 terminal=mt5.terminal_info()
 report={'created_utc':datetime.now(timezone.utc).isoformat(),'mode':'READ_ONLY','account':{'currency':getattr(account,'currency',None),'leverage':getattr(account,'leverage',None),'trade_allowed':getattr(account,'trade_allowed',None),'balance':getattr(account,'balance',None)},'terminal':{'trade_allowed':getattr(terminal,'trade_allowed',None)},'symbols':{}}
 for symbol in a.symbols:
  info=mt5.symbol_info(symbol)
  if info is None:
   report['symbols'][symbol]={'error':'symbol_not_found'};continue
  if not info.visible:mt5.symbol_select(symbol,True)
  entry={'point':info.point,'digits':info.digits,'trade_tick_size':info.trade_tick_size,'trade_tick_value':info.trade_tick_value,'trade_contract_size':info.trade_contract_size,'volume_min':info.volume_min,'volume_step':info.volume_step,'volume_max':info.volume_max,'trade_stops_level':info.trade_stops_level,'trade_freeze_level':info.trade_freeze_level,'spread_points_snapshot':info.spread,'spread_float':info.spread_float,'trade_mode':info.trade_mode,'trade_calc_mode':info.trade_calc_mode,'samples':[]}
  for i in range(a.samples):
   tick=mt5.symbol_info_tick(symbol)
   if tick and tick.bid>0 and tick.ask>tick.bid:
    spread=tick.ask-tick.bid
    entry['samples'].append({'timestamp_utc':datetime.fromtimestamp(tick.time,tz=timezone.utc).isoformat(),'bid':tick.bid,'ask':tick.ask,'spread_price':round(spread,info.digits+2),'spread_points':round(spread/info.point,2),'spread_pips':round(spread/(.0001 if 'JPY' not in symbol else .01),3)})
   if i<a.samples-1:time.sleep(a.interval)
  vals=[v['spread_pips'] for v in entry['samples']]
  if vals:entry['spread_pips_summary']={'min':min(vals),'median':statistics.median(vals),'max':max(vals),'n':len(vals)}
  report['symbols'][symbol]=entry
 path=Path(a.out);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Diagnóstico guardado:',path.resolve())
 print(json.dumps({s:{'volume_min':v.get('volume_min'),'contract_size':v.get('trade_contract_size'),'spread_pips':v.get('spread_pips_summary'),'error':v.get('error')} for s,v in report['symbols'].items()},indent=2))
finally:mt5.shutdown()
