"""V1.6: auditoría temporal y resultados observacionales, sin ejecución de órdenes."""
import json
import math
from datetime import datetime, timezone

MODEL = 'deterministic_audit_v1_6_1'
HORIZONS = (3, 6, 12)


def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS audit_v16 (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL, candle_time INTEGER NOT NULL,
      observed_at TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
      context_json TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'live',
      UNIQUE(symbol,candle_time,source))''')
    db.execute('''CREATE TABLE IF NOT EXISTS outcomes_v16 (
      audit_id INTEGER NOT NULL, horizon INTEGER NOT NULL,
      end_candle_time INTEGER NOT NULL, gross_return REAL NOT NULL,
      spread_cost_estimate REAL, net_return_estimate REAL,
      PRIMARY KEY(audit_id,horizon),
      FOREIGN KEY(audit_id) REFERENCES audit_v16(id))''')
    db.commit()


def ema(xs, period):
    if len(xs) < period:
        return None
    value = sum(xs[:period]) / period
    alpha = 2 / (period + 1)
    for x in xs[period:]:
        value = alpha * x + (1-alpha) * value
    return value


def atr(candles, period=14):
    if len(candles) < period+1:
        return None
    trs = []
    for prev, cur in zip(candles[:-1], candles[1:]):
        trs.append(max(cur['high']-cur['low'], abs(cur['high']-prev['close']), abs(cur['low']-prev['close'])))
    value = sum(trs[:period])/period
    for tr in trs[period:]:
        value = (value*(period-1)+tr)/period
    return value


def build(symbol, m5, m15, h1, quote=None):
    if not m5:
        raise ValueError('Sin M5')
    current = m5[-1]
    if len(m5) < 2:
        raise ValueError('Historial M5 insuficiente')
    cutoff = current['time']+300
    for tf, series, seconds in [('M5',m5,300),('M15',m15,900),('H1',h1,3600)]:
        if any(c['time']+seconds>cutoff for c in series):
            raise ValueError(f'LOOKAHEAD detectado en {tf}')
        if any(b['time']<=a['time'] for a,b in zip(series,series[1:])):
            raise ValueError(f'Orden temporal inválido en {tf}')
        if any(c['time'] % seconds != 0 for c in series):
            raise ValueError(f'Alineación temporal inválida en {tf}')
        if any(c['high'] < max(c['open'],c['close']) or c['low'] > min(c['open'],c['close']) or c['low'] <= 0 for c in series):
            raise ValueError(f'OHLC inválido en {tf}')
    if current['time'] + 300 != cutoff:
        raise ValueError('Cierre M5 inválido')
    closes = [c['close'] for c in h1]
    e20,e50,e200 = (ema(closes,p) for p in (20,50,200))
    trend = 'INSUFICIENTE' if e20 is None or e50 is None else ('ALCISTA' if e20>e50 and closes[-1]>e20 else 'BAJISTA' if e20<e50 and closes[-1]<e20 else 'MIXTA')
    a15 = atr(m15)
    a5 = atr(m5)
    structure = 'INSUFICIENTE'
    strength = None
    if len(m15)>=11:
        prev=m15[-11:-1]
        hi=max(c['high'] for c in prev)
        lo=min(c['low'] for c in prev)
        close=m15[-1]['close']
        structure='RUPTURA_ALCISTA' if close>hi else 'RUPTURA_BAJISTA' if close<lo else 'RANGO'
        if a15 and a15>0:
            strength=round(max(0,close-hi,lo-close)/a15,5)
    body=abs(current['close']-current['open'])
    candle_range=current['high']-current['low']
    ratio=round(body/candle_range,5) if candle_range>0 else 0
    direction='ALCISTA' if current['close']>current['open'] else 'BAJISTA' if current['close']<current['open'] else 'NEUTRA'
    aligned=((trend=='ALCISTA' and structure=='RUPTURA_ALCISTA' and direction=='ALCISTA') or (trend=='BAJISTA' and structure=='RUPTURA_BAJISTA' and direction=='BAJISTA'))
    decision='OBSERVAR' if aligned and ratio>=0.5 else 'ESPERAR'
    reason='Alineación técnica observacional; NO señal operable' if decision=='OBSERVAR' else 'Alineación insuficiente o datos incompletos'
    # Spread es una cotización instantánea, NO spread histórico de la vela.
    spread = quote if quote and quote.get('sampled_at') and quote['sampled_at']>=cutoff else None
    context={
      'symbol':symbol,'candle_time':current['time'],'candle_close_time':cutoff,
      'h1':{'trend':trend,'ema20':e20,'ema50':e50,'ema200':e200,'atr14':atr(h1),'last_closed_time':h1[-1]['time'] if h1 else None},
      'm15':{'structure':structure,'bos_strength_atr':strength,'atr14':a15,'last_closed_time':m15[-1]['time'] if m15 else None},
      'm5':{'direction':direction,'body_ratio':ratio,'close':current['close'],'atr14':a5,'volume':current['volume']},
      'spread_snapshot':spread,'spread_is_historical':False,
      'data_counts':{'h1':len(h1),'m15':len(m15),'m5':len(m5)},
      'temporal_validation':'PASS','model':MODEL,'orders_enabled':False,
      'source':'live','outcome_status':'pending'
    }
    return decision,reason,context


def insert(db, symbol, decision, reason, context):
    init(db)
    cur=db.execute('''INSERT OR IGNORE INTO audit_v16
      (symbol,candle_time,observed_at,decision,reason,context_json,source)
      VALUES (?,?,?,?,?,?,?)''', (symbol,context['candle_time'],datetime.now(timezone.utc).isoformat(),decision,reason,json.dumps(context,allow_nan=False),'live'))
    db.commit()
    return cur.rowcount>0


def update_outcomes(db, symbol, m5):
    """Horizontes medidos desde el cierre de la vela observada.

    El horizonte 3 termina en la vela que abre tres intervalos M5 después
    de la observada; no se permite interpolar huecos ni usar velas abiertas.
    """
    init(db)
    by_time = {c['time']: c for c in m5}
    rows = db.execute('SELECT id,candle_time,context_json FROM audit_v16 WHERE symbol=? AND source=?', (symbol,'live')).fetchall()
    count = 0
    for row in rows:
        ctx = json.loads(row['context_json'])
        start = ctx['m5']['close']
        for horizon in HORIZONS:
            target = row['candle_time'] + horizon * 300
            if target not in by_time:
                continue
            # No evaluar si faltan velas intermedias.
            if any(row['candle_time'] + k*300 not in by_time for k in range(1,horizon+1)):
                continue
            if db.execute('SELECT 1 FROM outcomes_v16 WHERE audit_id=? AND horizon=?', (row['id'],horizon)).fetchone():
                continue
            end = by_time[target]['close']
            gross = (end-start)/start
            # El spread instantáneo fue observado después del cierre: NO es
            # válido para imputar costos históricos. Conservamos NULL.
            db.execute('INSERT OR IGNORE INTO outcomes_v16 VALUES (?,?,?,?,?,?)',
                       (row['id'],horizon,target,gross,None,None))
            count += 1
    db.commit()
    return count

def list_audit(db,symbol=None,limit=50):
    init(db)
    if symbol:
        rows=db.execute('SELECT * FROM audit_v16 WHERE symbol=? ORDER BY candle_time DESC LIMIT ?',(symbol,limit)).fetchall()
    else:
        rows=db.execute('SELECT * FROM audit_v16 ORDER BY candle_time DESC LIMIT ?',(limit,)).fetchall()
    result=[]
    for r in rows:
        d=dict(r)
        d['context']=json.loads(d.pop('context_json'))
        d['outcomes']=[{**dict(x), 'spread_cost_estimate':None, 'net_return_estimate':None} for x in db.execute('SELECT horizon,end_candle_time,gross_return,spread_cost_estimate,net_return_estimate FROM outcomes_v16 WHERE audit_id=? ORDER BY horizon',(r['id'],)).fetchall()]
        result.append(d)
    return result


def metrics(db):
    init(db)
    counts=[dict(r) for r in db.execute('SELECT symbol,decision,COUNT(*) AS count FROM audit_v16 GROUP BY symbol,decision ORDER BY symbol,decision')]
    outcomes=[dict(r) for r in db.execute('''SELECT a.symbol,o.horizon,COUNT(*) AS count,AVG(o.gross_return) AS mean_gross_return,
      NULL AS mean_net_estimate,
      0 AS priced_count
      FROM outcomes_v16 o JOIN audit_v16 a ON a.id=o.audit_id
      GROUP BY a.symbol,o.horizon ORDER BY a.symbol,o.horizon''')]
    audit_total = db.execute('SELECT COUNT(*) FROM audit_v16').fetchone()[0]
    legacy_total = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0] if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations'").fetchone() else 0
    outcome_total = db.execute('SELECT COUNT(*) FROM outcomes_v16').fetchone()[0]
    return {'counts':counts,'forward_outcomes':outcomes,'audit_total':audit_total,'legacy_total':legacy_total,'outcome_total':outcome_total,'unit':'fractional_return','note':'Retornos descriptivos sin costos ejecutables. Spread posterior NO se utiliza como histórico. Sin P/L, comisiones ni slippage.'}
