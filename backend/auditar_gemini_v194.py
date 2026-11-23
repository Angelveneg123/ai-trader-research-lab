"""Auditoría de decisiones Gemini V1.9.4. Solo lectura, sin API ni MT5."""
import argparse, csv, json, math, sqlite3, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo('America/Managua')
PIP = 0.0001

def evaluate(d, candles, spread_pips):
    problems=[]
    side=d['decision']; asof=datetime.fromisoformat(d['decision_time_utc'].replace('Z','+00:00')).astimezone(timezone.utc)
    local=asof.astimezone(TZ)
    base={'decision_id':d['decision_id'],'decision_time_utc':d['decision_time_utc'], 'decision':side,
          'confidence':d['confidence'],'outcome':'INDETERMINATE','gross_pips':None,'net_pips_scenario':None,
          'bars_checked':0,'exit_time_utc':'','entry_reference':None,'exit_reference':None,'issues':''}
    try:
        context=json.loads(d['context_json']); entry=float(context['candles']['M5'][-1]['close'])
        base['entry_reference']=entry
        for tf,step in [('M5',300),('M15',900),('H1',3600)]:
            cs=context['candles'][tf]
            if not cs or any(int(c['candle_time'])+step>int(asof.timestamp()) for c in cs):
                problems.append('LOOKAHEAD_'+tf)
            if any(int(b['candle_time'])<=int(a['candle_time']) for a,b in zip(cs,cs[1:])):
                problems.append('CONTEXT_ORDER_'+tf)
        if context.get('decision_time_utc')!=d['decision_time_utc']: problems.append('CONTEXT_TIME_MISMATCH')
    except (ValueError,KeyError,TypeError,IndexError) as e:
        base['issues']='CONTEXT_INVALID:'+str(e);return base
    if not (time(2)<=local.time().replace(tzinfo=None)<time(10)):
        problems.append('OUT_OF_SESSION')
    if side=='WAIT':
        base['outcome']='WAIT';base['issues']=';'.join(problems);return base
    if side not in ('BUY','SELL'):
        problems.append('INVALID_SIDE');base['issues']=';'.join(problems);return base
    sl,tp=d['stop_loss'],d['take_profit']
    if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>0 for x in (sl,tp)):
        problems.append('INVALID_SL_TP');base['issues']=';'.join(problems);return base
    if not ((sl<entry<tp) if side=='BUY' else (tp<entry<sl)):
        problems.append('LEVELS_NOT_AROUND_ENTRY');base['issues']=';'.join(problems);return base
    end_local=datetime.combine(local.date(),time(10),tzinfo=TZ)
    max_bars=int((end_local.astimezone(timezone.utc)-asof).total_seconds()/300)
    if max_bars<=0:
        base['issues']=';'.join(problems+['NO_SESSION_TIME']);return base
    expected=int(asof.timestamp())
    for i in range(max_bars):
        if i>=len(candles) or candles[i]['candle_time']!=expected:
            problems.append('MISSING_FUTURE_M5');break
        c=candles[i];expected+=300;base['bars_checked']=i+1
        if not all(math.isfinite(c[k]) for k in ('open','high','low','close')) or not (c['low']<=min(c['open'],c['close'])<=max(c['open'],c['close'])<=c['high']):
            problems.append('INVALID_OHLC');break
        if i==0 and (c['open']<=min(sl,tp) or c['open']>=max(sl,tp)):
            problems.append('OPEN_GAP_PAST_LEVEL');break
        hit_sl=c['low']<=sl if side=='BUY' else c['high']>=sl
        hit_tp=c['high']>=tp if side=='BUY' else c['low']<=tp
        if hit_sl and hit_tp:
            problems.append('BOTH_LEVELS_SAME_BAR');break
        if hit_sl or hit_tp:
            base['outcome']='LOSS' if hit_sl else 'WIN'
            base['exit_reference']=sl if hit_sl else tp
        elif i==max_bars-1:
            base['outcome']='SESSION_CLOSE';base['exit_reference']=c['close']
        else:continue
        base['exit_time_utc']=datetime.fromtimestamp(c['candle_time']+300,timezone.utc).isoformat()
        base['gross_pips']=round((base['exit_reference']-entry)/PIP*(1 if side=='BUY' else -1),2)
        base['net_pips_scenario']=round(base['gross_pips']-spread_pips,2)
        break
    base['issues']=';'.join(problems)
    return base

def main():
    p=argparse.ArgumentParser(description='Auditoría histórica de solo lectura; NO llama APIs')
    p.add_argument('--history',type=Path,default=ROOT/'data'/'historical.sqlite3')
    p.add_argument('--journal',type=Path,default=ROOT/'data'/'ai_decisions.sqlite3')
    p.add_argument('--output',type=Path,default=ROOT/'data'/'audit_v194')
    p.add_argument('--spread-pips',type=float,default=1.0,help='Escenario hipotético de costo total en pips; no es costo real')
    args=p.parse_args()
    if not 0<=args.spread_pips<=100 or not math.isfinite(args.spread_pips):p.error('Costo inválido')
    if not args.history.is_file() or not args.journal.is_file():p.error('Faltan bases SQLite en data/')
    with sqlite3.connect(f'file:{args.history.resolve().as_posix()}?mode=ro',uri=True) as hist,sqlite3.connect(f'file:{args.journal.resolve().as_posix()}?mode=ro',uri=True) as journal:
        hist.row_factory=sqlite3.Row;journal.row_factory=sqlite3.Row
        decisions=[dict(x) for x in journal.execute('SELECT * FROM ai_historical_decisions ORDER BY decision_time_utc')]
        tables={x[0] for x in journal.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        previous={x['decision_id']:dict(x) for x in journal.execute('SELECT * FROM ai_session_evaluations_v192')} if 'ai_session_evaluations_v192' in tables else {}
        results=[]
        for d in decisions:
            ts=int(datetime.fromisoformat(d['decision_time_utc'].replace('Z','+00:00')).timestamp())
            cs=[dict(x) for x in hist.execute("SELECT candle_time,open,high,low,close FROM historical_candles WHERE symbol=? AND timeframe='M5' AND candle_time>=? ORDER BY candle_time LIMIT 110",(d['symbol'],ts))]
            r=evaluate(d,cs,args.spread_pips)
            r['symbol']=d['symbol'];r['model']=d['model']
            r['v192_outcome']=previous.get(d['decision_id'],{}).get('outcome','NOT_RECORDED')
            r['v192_mismatch']=bool(r['v192_outcome']!='NOT_RECORDED' and r['v192_outcome']!=r['outcome'])
            results.append(r)
    args.output.mkdir(parents=True,exist_ok=True)
    cols=['decision_id','decision_time_utc','symbol','model','decision','confidence','entry_reference','exit_reference','outcome','gross_pips','net_pips_scenario','bars_checked','exit_time_utc','v192_outcome','v192_mismatch','issues']
    with (args.output/'audit_detail.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(results)
    by_conf=defaultdict(lambda:Counter())
    for r in results:
        c=r['confidence']; bucket='INVALID' if not isinstance(c,(int,float)) or not 0<=c<=1 else ('0-49%' if c<.5 else '50-69%' if c<.7 else '70-84%' if c<.85 else '85-100%')
        by_conf[bucket][r['outcome']]+=1
    known=[r for r in results if r['gross_pips'] is not None]
    summary={'decisions':len(results),'directions':dict(Counter(r['decision'] for r in results)),
             'outcomes':dict(Counter(r['outcome'] for r in results)),
             'gross_pips_sum_reference':round(sum(r['gross_pips'] for r in known),2),
             'net_pips_sum_hypothetical':round(sum(r['net_pips_scenario'] for r in known),2),
             'hypothetical_cost_per_trade_pips':args.spread_pips,
             'evaluated_trades_with_pips':len(known),
             'v192_mismatches':sum(r['v192_mismatch'] for r in results),
             'flagged_records':sum(bool(r['issues']) for r in results),
             'by_confidence':{k:dict(v) for k,v in sorted(by_conf.items())},
             'limitations':['Precios de entrada/salida son referencias OHLC, no bid/ask ni fills reales',
                            'El costo fijo es hipotético y no incluye deslizamiento variable',
                            'El orden intrabar es desconocido; coincidencia SL/TP se marca INDETERMINATE',
                            'Una muestra de 11 no prueba ventaja estadística',
                            'No se modifica ninguna base de datos ni se llama a Gemini']}
    (args.output/'audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('Archivos:',args.output/'audit_detail.csv',args.output/'audit_summary.json')
if __name__=='__main__':
    try:main()
    except Exception as exc:print(f'ERROR: {type(exc).__name__}: {exc}',file=sys.stderr);sys.exit(1)
