"""V1.7: importación histórica reproducible; jamás escribe en research.sqlite3."""
import argparse
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .mt5_market import SECONDS, SYMBOLS, TIMEFRAMES
from .mt5_connection import ipc_lock

DEFAULT_DB = Path(__file__).resolve().parents[2] / 'data' / 'historical.sqlite3'
START = datetime(2026, 8, 1, tzinfo=timezone.utc)


def connect(path=None):
    path = Path(path or os.getenv('HISTORICAL_DB', str(DEFAULT_DB)))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=30000')
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS historical_candles (
        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_time INTEGER NOT NULL,
        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
        tick_volume INTEGER NOT NULL, spread_points INTEGER, real_volume INTEGER,
        source TEXT NOT NULL DEFAULT 'deriv_mt5_historical', imported_at TEXT NOT NULL,
        PRIMARY KEY(symbol,timeframe,candle_time));
      CREATE TABLE IF NOT EXISTS import_runs (
        run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
        requested_from TEXT NOT NULL, requested_to TEXT NOT NULL,
        status TEXT NOT NULL, summary_json TEXT);
      CREATE TABLE IF NOT EXISTS import_segments (
        run_id TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
        start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
        received INTEGER NOT NULL, inserted INTEGER NOT NULL, duplicates INTEGER NOT NULL,
        invalid INTEGER NOT NULL, status TEXT NOT NULL, error TEXT,
        FOREIGN KEY(run_id) REFERENCES import_runs(run_id));
      CREATE TABLE IF NOT EXISTS rejected_candles (
        run_id TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
        segment_start TEXT NOT NULL, candle_time INTEGER, reason TEXT NOT NULL,
        recorded_at TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS ix_hist_time ON historical_candles(timeframe,candle_time);
    ''')
    db.commit()
    return db


def validate_rate(r, seconds, start_ts, end_ts, now_ts):
    try:
        t = int(r['time'])
        o, h, l, c = (float(r[k]) for k in ('open', 'high', 'low', 'close'))
        vol = int(r['tick_volume'])
        spread = int(r['spread']) if 'spread' in r.dtype.names else None
        real = int(r['real_volume']) if 'real_volume' in r.dtype.names else None
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return None
    import math
    if not all(math.isfinite(x) for x in (o,h,l,c)) or min(o,h,l,c) <= 0:
        return None
    if h < max(o,c,l) or l > min(o,c,h) or vol < 0:
        return None
    if t % seconds or not start_ts <= t < end_ts or t+seconds > now_ts:
        return None
    if spread is not None and spread < 0:
        return None
    return (t,o,h,l,c,vol,spread,real)


def quality(db, symbol, timeframe, from_ts=None, to_ts=None):
    sql = 'SELECT candle_time,open,high,low,close FROM historical_candles WHERE symbol=? AND timeframe=?'
    args = [symbol,timeframe]
    if from_ts is not None:
        sql += ' AND candle_time>=?'; args.append(from_ts)
    if to_ts is not None:
        sql += ' AND candle_time<?'; args.append(to_ts)
    sql += ' ORDER BY candle_time'
    rows = db.execute(sql,args).fetchall()
    step=SECONDS[timeframe]
    gaps=[]
    for prev,cur in zip(rows,rows[1:]):
        missing=(cur['candle_time']-prev['candle_time'])//step-1
        if missing>0:
            gaps.append({'after':prev['candle_time'],'before':cur['candle_time'],'missing_intervals':missing})
    return {'symbol':symbol,'timeframe':timeframe,'candles':len(rows),
            'first_time':rows[0]['candle_time'] if rows else None,
            'last_time':rows[-1]['candle_time'] if rows else None,
            'gap_count':len(gaps),'missing_intervals':sum(x['missing_intervals'] for x in gaps),
            'gaps_preview':gaps[:30],
            'gap_note':'Los fines de semana y cierres de mercado pueden producir huecos normales; no se interpolan.'}


def import_history(db, mt5, start=START, end=None, symbols=SYMBOLS, timeframes=('M5','M15','H1'), chunk_days=5):
    now = datetime.now(timezone.utc)
    end = min(end or now, now)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError('Fechas deben incluir zona horaria')
    start,end=start.astimezone(timezone.utc),end.astimezone(timezone.utc)
    if not START <= start < end:
        raise ValueError('Rango inválido; mínimo 2026-08-01 UTC')
    if chunk_days<1 or chunk_days>14:
        raise ValueError('chunk_days debe estar entre 1 y 14')
    if any(s not in SYMBOLS for s in symbols) or any(t not in TIMEFRAMES for t in timeframes):
        raise ValueError('Símbolo o timeframe inválido')
    run_id=uuid.uuid4().hex
    started=datetime.now(timezone.utc).isoformat()
    db.execute('INSERT INTO import_runs(run_id,started_at,requested_from,requested_to,status) VALUES (?,?,?,?,?)',
               (run_id,started,start.isoformat(),end.isoformat(),'running'))
    db.commit()
    summary={'run_id':run_id,'segments':0,'received':0,'inserted':0,'duplicates':0,'invalid':0,'empty_segments':0,'errors':[], 'quality':[]}
    with ipc_lock():
        if not mt5.initialize():
            err=f'No se pudo conectar MT5: {mt5.last_error()}'
            db.execute('UPDATE import_runs SET status=?,finished_at=?,summary_json=? WHERE run_id=?',
                       ('failed',datetime.now(timezone.utc).isoformat(),json.dumps({'error':err}),run_id))
            db.commit()
            raise RuntimeError(err)
        try:
            account=mt5.account_info()
            if not account or account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
                raise RuntimeError('La importación exige una cuenta MT5 DEMO')
            for symbol in symbols:
                if not mt5.symbol_select(symbol,True):
                    summary['errors'].append(f'{symbol}: símbolo no disponible')
                    continue
                for tf in timeframes:
                    step=SECONDS[tf]
                    cursor=start
                    while cursor<end:
                        upper=min(cursor+timedelta(days=chunk_days),end)
                        # copy_rates_range incluye ambos extremos; se filtra [cursor,upper).
                        # Solo pedimos hasta el último inicio de vela del segmento.
                        request_end=upper-timedelta(seconds=1)
                        status='ok'; error=None
                        try:
                            rates=mt5.copy_rates_range(symbol,TIMEFRAMES[tf],cursor,request_end)
                            if rates is None:
                                raise RuntimeError(str(mt5.last_error()))
                            received=len(rates)
                            valid={}
                            invalid=0
                            for r in rates:
                                item=validate_rate(r,step,int(cursor.timestamp()),int(upper.timestamp()),int(now.timestamp()))
                                if item is None:
                                    invalid+=1
                                    try:
                                        rejected_time=int(r['time'])
                                    except (KeyError,TypeError,ValueError,OverflowError):
                                        rejected_time=None
                                    # Identifica la categoría sin guardar información de precios innecesaria.
                                    reason='validation_failed'
                                    if rejected_time is not None:
                                        if rejected_time % step: reason='misaligned_timestamp'
                                        elif not int(cursor.timestamp()) <= rejected_time < int(upper.timestamp()): reason='outside_requested_segment'
                                        elif rejected_time+step > int(now.timestamp()): reason='unclosed_candle'
                                        else: reason='invalid_ohlc_volume_or_spread'
                                    db.execute('''INSERT INTO rejected_candles
                                        (run_id,symbol,timeframe,segment_start,candle_time,reason,recorded_at)
                                        VALUES (?,?,?,?,?,?,?)''',
                                        (run_id,symbol,tf,cursor.isoformat(),rejected_time,reason,datetime.now(timezone.utc).isoformat()))
                                else:
                                    valid[item[0]]=item
                            inserted=0
                            imported_at=datetime.now(timezone.utc).isoformat()
                            for t,o,h,l,c,v,sp,rv in valid.values():
                                cur=db.execute('''INSERT OR IGNORE INTO historical_candles
                                  (symbol,timeframe,candle_time,open,high,low,close,tick_volume,spread_points,real_volume,imported_at)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                                  (symbol,tf,t,o,h,l,c,v,sp,rv,imported_at))
                                inserted+=cur.rowcount
                            duplicates=len(valid)-inserted
                            if received==0:
                                status='empty'
                                summary['empty_segments']+=1
                            summary['received']+=received
                            summary['inserted']+=inserted
                            summary['duplicates']+=duplicates
                            summary['invalid']+=invalid
                        except Exception as exc:
                            received=inserted=duplicates=invalid=0
                            status='error'; error=str(exc)
                            summary['errors'].append(f'{symbol}/{tf} {cursor.isoformat()}: {error}')
                        db.execute('''INSERT INTO import_segments
                          (run_id,symbol,timeframe,start_utc,end_utc,received,inserted,duplicates,invalid,status,error)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                          (run_id,symbol,tf,cursor.isoformat(),upper.isoformat(),received,inserted,duplicates,invalid,status,error))
                        db.commit()
                        summary['segments']+=1
                        cursor=upper
                    summary['quality'].append(quality(db,symbol,tf,int(start.timestamp()),int(end.timestamp())))
        except Exception as exc:
            summary['errors'].append(str(exc))
        finally:
            mt5.shutdown()
    status='partial' if summary['errors'] else 'completed'
    db.execute('UPDATE import_runs SET status=?,finished_at=?,summary_json=? WHERE run_id=?',
               (status,datetime.now(timezone.utc).isoformat(),json.dumps(summary),run_id))
    db.commit()
    return {'status':status,**summary}


def status(db):
    run=db.execute('SELECT * FROM import_runs ORDER BY started_at DESC LIMIT 1').fetchone()
    counts=[dict(x) for x in db.execute('''SELECT symbol,timeframe,COUNT(*) count,MIN(candle_time) first_time,MAX(candle_time) last_time
      FROM historical_candles GROUP BY symbol,timeframe ORDER BY symbol,timeframe''')]
    return {'storage':'separate_sqlite','source':'deriv_mt5_historical','last_run':dict(run) if run else None,
            'series':counts,'orders_enabled':False,'ai_connected':False,
            'warning':'La presencia de velas no demuestra cobertura completa. Consultar quality y segmentos.'}


def main():
    parser=argparse.ArgumentParser(description='V1.7 importación histórica MT5 demo, sin órdenes')
    parser.add_argument('--from-date',default='2026-08-01')
    parser.add_argument('--to-date',default=None,help='Fecha UTC exclusiva YYYY-MM-DD; por defecto ahora')
    parser.add_argument('--db',default=None)
    parser.add_argument('--chunk-days',type=int,default=5)
    args=parser.parse_args()
    start=datetime.fromisoformat(args.from_date).replace(tzinfo=timezone.utc)
    end=datetime.fromisoformat(args.to_date).replace(tzinfo=timezone.utc) if args.to_date else None
    import MetaTrader5 as mt5
    with connect(args.db) as db:
        print(json.dumps(import_history(db,mt5,start,end,chunk_days=args.chunk_days),indent=2,ensure_ascii=False))

if __name__=='__main__':
    main()
