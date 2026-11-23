"""V1.7.1: diagnóstico de solo lectura sobre historical.sqlite3.
No modifica velas ni rellena huecos; clasificaciones conservadoras, no calendario de broker.
"""
from collections import Counter
from datetime import datetime, timezone
from .mt5_market import SECONDS, SYMBOLS, TIMEFRAMES


def _utc(ts):
    return datetime.fromtimestamp(ts,timezone.utc).isoformat()


def classify_gap(symbol, timeframe, left, right):
    step=SECONDS[timeframe]
    missing=(right-left)//step-1
    # Es una heurística, NO prueba de que el mercado estuviera cerrado.
    if missing <= 0:
        return 'none'
    a=datetime.fromtimestamp(left,timezone.utc)
    b=datetime.fromtimestamp(right,timezone.utc)
    if (b-a).total_seconds() >= 36*3600 and any(
        datetime.fromtimestamp(left+step*i,timezone.utc).weekday() >= 5
        for i in range(1,min(missing+1,2000))
    ):
        return 'probable_weekend'
    if symbol=='XAUUSD' and missing*step <= 3*3600 and a.date()!=b.date():
        return 'possible_daily_pause'
    return 'requires_review'


def gap_report(db,symbol,timeframe,limit=100):
    if symbol not in SYMBOLS or timeframe not in TIMEFRAMES:
        raise ValueError('Símbolo o temporalidad no permitida')
    if not 1 <= limit <= 1000:
        raise ValueError('limit fuera de rango')
    rows=db.execute('SELECT candle_time FROM historical_candles WHERE symbol=? AND timeframe=? ORDER BY candle_time', (symbol,timeframe)).fetchall()
    step=SECONDS[timeframe]
    counts=Counter(); missing_counts=Counter(); items=[]
    for prev,cur in zip(rows,rows[1:]):
        left,right=prev['candle_time'],cur['candle_time']
        missing=(right-left)//step-1
        if missing<=0:continue
        kind=classify_gap(symbol,timeframe,left,right)
        counts[kind]+=1;missing_counts[kind]+=missing
        if len(items)<limit:
            items.append({'after':left,'before':right,'after_utc':_utc(left),'before_utc':_utc(right),'missing_intervals':missing,'classification':kind})
    return {'symbol':symbol,'timeframe':timeframe,'candles':len(rows),'gap_count':sum(counts.values()),
            'missing_intervals':sum(missing_counts.values()),'gap_types':dict(counts),'missing_by_type':dict(missing_counts),
            'gaps_preview':items,'classification_warning':'Heurística UTC; confirmar horarios y festivos de Deriv. No se interpolan datos.'}


def alignment_report(db,symbol,limit=50):
    if symbol not in SYMBOLS:raise ValueError('Símbolo no permitido')
    if not 1<=limit<=500:raise ValueError('limit fuera de rango')
    # Se compara por apertura UTC. Una M15 debe tener hasta 3 M5; H1 hasta 12 M5.
    # No inferimos ausencias cuando falta la vela superior.
    output={}
    for tf,expected in [('M15',3),('H1',12)]:
        high_times=[r['candle_time'] for r in db.execute('SELECT candle_time FROM historical_candles WHERE symbol=? AND timeframe=? ORDER BY candle_time',(symbol,tf))]
        m5_times={r['candle_time'] for r in db.execute('SELECT candle_time FROM historical_candles WHERE symbol=? AND timeframe=?',(symbol,'M5'))}
        anomalies=[]; incomplete=0;complete=0
        for t in high_times:
            present=sum((t+300*i) in m5_times for i in range(expected))
            if present==expected:complete+=1
            else:
                incomplete+=1
                if len(anomalies)<limit:
                    anomalies.append({'higher_open':t,'higher_open_utc':_utc(t),'m5_present':present,'m5_expected':expected,'m5_missing':expected-present})
        output[tf]={'higher_candles':len(high_times),'complete_m5_windows':complete,'incomplete_m5_windows':incomplete,'anomalies_preview':anomalies}
    return {'symbol':symbol,'alignment':output,'note':'Compara existencia y alineación UTC, no igualdad OHLC ni horarios de sesión; no se crean velas.'}


def rejected_report(db):
    # V1.7 guardaba solo el total por segmento: los nueve motivos no son recuperables retrospectivamente.
    runs=[dict(r) for r in db.execute('SELECT run_id,started_at,status FROM import_runs ORDER BY started_at DESC LIMIT 10')]
    data=[]
    for run in runs:
        segs=[dict(r) for r in db.execute('''SELECT symbol,timeframe,start_utc,end_utc,invalid,status,error
                 FROM import_segments WHERE run_id=? AND (invalid>0 OR status='error') ORDER BY symbol,timeframe,start_utc''',(run['run_id'],))]
        data.append({'run_id':run['run_id'],'started_at':run['started_at'],'invalid_total':sum(x['invalid'] for x in segs),'segments':segs})
    details=[dict(r) for r in db.execute('SELECT run_id,symbol,timeframe,segment_start,candle_time,reason FROM rejected_candles ORDER BY recorded_at DESC LIMIT 200')]
    return {'runs':data,'individual_rejection_reasons_available':bool(details), 'recorded_rejections':details,
            'note':'Los rechazos de V1.7 solo se conservaron como totales por segmento. Las nuevas importaciones V1.7.1 registran categoría y hora; para investigar los 9 anteriores, reimportar los segmentos afectados.'}
