"""V1.9.5: auditoría de selección, sensibilidad y referencia aleatoria. Solo lectura."""
import argparse, csv, json, math, random, sqlite3, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
PIP = 0.0001
TZ = ZoneInfo('America/Managua')
COSTS = [0.5, 1.0, 1.5, 2.0]

def outcome(side, entry, sl, tp, ts, bars):
    local = datetime.fromtimestamp(ts, timezone.utc).astimezone(TZ)
    end = local.replace(hour=10, minute=0, second=0, microsecond=0)
    end_ts = int(end.timestamp())
    if end_ts <= ts:
        return None, 'OUT_OF_SESSION'
    expected = ts
    for bar in bars:
        if expected >= end_ts: break
        if int(bar['candle_time']) != expected:
            return None, 'MISSING_BAR'
        if not (bar['low'] <= min(bar['open'],bar['close']) <= max(bar['open'],bar['close']) <= bar['high']):
            return None, 'INVALID_OHLC'
        if bar['open'] <= min(sl,tp) or bar['open'] >= max(sl,tp):
            return None, 'OPEN_OUTSIDE_LEVELS'
        hit_sl = bar['low'] <= sl if side == 'BUY' else bar['high'] >= sl
        hit_tp = bar['high'] >= tp if side == 'BUY' else bar['low'] <= tp
        if hit_sl and hit_tp: return None, 'AMBIGUOUS_INTRABAR'
        if hit_sl or hit_tp:
            exit_price = sl if hit_sl else tp
            return round((exit_price-entry)/PIP*(1 if side=='BUY' else -1), 6), ('LOSS' if hit_sl else 'WIN')
        expected += 300
        if expected == end_ts:
            return round((bar['close']-entry)/PIP*(1 if side=='BUY' else -1), 6), 'SESSION_CLOSE'
    return None, 'MISSING_BAR'

def main():
    p=argparse.ArgumentParser(description='V1.9.5: solo lectura, sin API, sin MT5')
    p.add_argument('--history', type=Path, default=ROOT/'data'/'historical.sqlite3')
    p.add_argument('--journal', type=Path, default=ROOT/'data'/'ai_decisions.sqlite3')
    p.add_argument('--out', type=Path, default=ROOT/'data'/'audit_v195')
    p.add_argument('--simulations', type=int, default=1000)
    p.add_argument('--seed', type=int, default=195)
    args=p.parse_args()
    if not 1 <= args.simulations <= 100000: p.error('simulations debe estar entre 1 y 100000')
    for path in (args.history,args.journal):
        if not path.is_file(): p.error(f'No existe {path}')
    uri=lambda path: f'file:{path.resolve().as_posix()}?mode=ro'
    with sqlite3.connect(uri(args.journal),uri=True) as j, sqlite3.connect(uri(args.history),uri=True) as h:
        j.row_factory=sqlite3.Row; h.row_factory=sqlite3.Row
        decisions=[dict(r) for r in j.execute('SELECT * FROM ai_historical_decisions WHERE symbol=? ORDER BY decision_time_utc',('EURUSD',))]
        records=[]; baseline=[]; issues=[]
        for d in decisions:
            ts=int(datetime.fromisoformat(d['decision_time_utc'].replace('Z','+00:00')).timestamp())
            local=datetime.fromtimestamp(ts,timezone.utc).astimezone(TZ)
            try:
                ctx=json.loads(d['context_json']); candles=ctx['candles']
                entry=float(candles['M5'][-1]['close'])
                if ctx.get('decision_time_utc')!=d['decision_time_utc']: issues.append([d['decision_id'],'CONTEXT_TIME'])
                for tf, step in [('M5',300),('M15',900),('H1',3600)]:
                    arr=candles[tf]
                    if not arr or any(int(x['candle_time'])+step>ts for x in arr): issues.append([d['decision_id'],'LOOKAHEAD_'+tf])
                    if any(int(b['candle_time'])<=int(a['candle_time']) for a,b in zip(arr,arr[1:])): issues.append([d['decision_id'],'ORDER_'+tf])
                if not (2 <= local.hour < 10): issues.append([d['decision_id'],'OUT_OF_SESSION'])
            except Exception as e:
                issues.append([d['decision_id'],'BAD_CONTEXT:'+str(e)]);continue
            rec={'decision_id':d['decision_id'],'date_local':local.date().isoformat(),'hour_local':local.hour,'decision':d['decision'],'confidence':d['confidence'],'entry':entry,'gross_pips':None,'outcome':'WAIT' if d['decision']=='WAIT' else 'UNRESOLVED','issues':''}
            if d['decision'] in ('BUY','SELL'):
                sl,tp=d['stop_loss'],d['take_profit']
                if not all(isinstance(v,(float,int)) and math.isfinite(v) for v in (sl,tp)) or not ((sl<entry<tp) if d['decision']=='BUY' else (tp<entry<sl)):
                    issues.append([d['decision_id'],'INVALID_LEVELS'])
                else:
                    rows=[dict(x) for x in h.execute('SELECT candle_time,open,high,low,close FROM historical_candles WHERE symbol=? AND timeframe=? AND candle_time>=? ORDER BY candle_time LIMIT 100',('EURUSD','M5',ts))]
                    gross,status=outcome(d['decision'],entry,sl,tp,ts,rows)
                    rec.update(gross_pips=gross,outcome=status)
                    if gross is None: issues.append([d['decision_id'],status])
                    else:
                        # Same entry and same SL/TP distances, with random BUY/SELL directions.
                        sl_dist=abs(entry-sl); tp_dist=abs(entry-tp)
                        alt={}
                        for direction in ('BUY','SELL'):
                            alt_sl=entry-sl_dist if direction=='BUY' else entry+sl_dist
                            alt_tp=entry+tp_dist if direction=='BUY' else entry-tp_dist
                            alt[direction]=outcome(direction,entry,alt_sl,alt_tp,ts,rows)
                        baseline.append((d['decision_id'],gross,alt))
            records.append(rec)
    days=[r['date_local'] for r in records]; hours=Counter(r['hour_local'] for r in records)
    if len(days)!=len(set(days)): issues.append(['SELECTION','MULTIPLE_SCENARIOS_SAME_DAY'])
    # The stored decisions alone cannot prove that candidate selection was independent of future outcomes.
    rng=random.Random(args.seed); sims=[]; invalid_sim=0
    for _ in range(args.simulations):
        total=0.0; valid=True
        for _,_,alt in baseline:
            direction=rng.choice(('BUY','SELL'))
            val,status=alt[direction]
            if val is None:
                valid=False;break
            total+=val
        if valid: sims.append(total)
        else: invalid_sim+=1
    actual=sum(g for _,g,_ in baseline)
    sensitivity=[{'cost_pips_per_trade':cost,'gross_pips':round(actual,2),'net_pips_hypothetical':round(actual-cost*len(baseline),2),'trades':len(baseline)} for cost in COSTS]
    sims.sort()
    summary={'decisions':len(records),'trade_signals':sum(r['decision'] in ('BUY','SELL') for r in records),'evaluable_trades':len(baseline),'unique_days':len(set(days)),'hours_local':dict(sorted(hours.items())),'outcomes':dict(Counter(r['outcome'] for r in records)),'gross_pips_reference':round(actual,2),'sensitivity':sensitivity,'random_baseline':{'method':'Aleatorizar BUY/SELL en las mismas entradas, con distancias SL/TP de cada señal; no simula WAIT ni política de selección','seed':args.seed,'requested_simulations':args.simulations,'valid_simulations':len(sims),'invalid_simulations':invalid_sim,'mean_gross_pips':round(sum(sims)/len(sims),2) if sims else None,'fraction_at_least_actual':round(sum(v>=actual for v in sims)/len(sims),4) if sims else None},'issues':issues,'limitations':['No puede verificarse ausencia de sesgo de selección solo con decisiones guardadas: requiere registrar universo de candidatos y reglas congeladas.','Referencia aleatoria condicionada a las entradas seleccionadas por Gemini; no es un benchmark independiente de extremo a extremo.','El precio de entrada es cierre OHLC de referencia, no fill bid/ask; costos fijos son escenarios hipotéticos.','La muestra piloto fue observada previamente; no es validación fuera de muestra.','No se ejecutan operaciones ni llamadas API.']}
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/'v195_detail.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=['decision_id','date_local','hour_local','decision','confidence','entry','gross_pips','outcome','issues']);w.writeheader();w.writerows(records)
    (args.out/'v195_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('Archivos:',args.out/'v195_detail.csv',args.out/'v195_summary.json')
if __name__=='__main__':
    try:main()
    except Exception as e:
        print(f'ERROR: {type(e).__name__}: {e}',file=sys.stderr);sys.exit(1)
