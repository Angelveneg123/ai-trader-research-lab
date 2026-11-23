"""V1.9.1: evalúa decisiones históricas usando velas M5 posteriores; nunca opera MT5."""
import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / 'data' / 'historical.sqlite3'
JOURNAL = ROOT / 'data' / 'ai_decisions.sqlite3'
STEP = 300
PIP = 0.0001  # EURUSD únicamente


def evaluate(decision, candles, horizon):
    """Devuelve un resultado conservador basado solo en OHLC, no en ticks bid/ask."""
    side = decision['decision']
    if side == 'WAIT':
        return {'outcome': 'WAIT', 'bars_checked': 0, 'exit_time_utc': None,
                'gross_pips_reference': None, 'detail': 'Sin operación hipotética'}
    sl, tp = decision['stop_loss'], decision['take_profit']
    if side not in ('BUY', 'SELL') or any(v is None or not math.isfinite(float(v)) or float(v) <= 0 for v in (sl, tp)):
        return {'outcome': 'INDETERMINATE', 'bars_checked': 0, 'exit_time_utc': None,
                'gross_pips_reference': None, 'detail': 'Decisión o SL/TP inválidos'}
    sl, tp = float(sl), float(tp)
    if (side == 'BUY' and sl >= tp) or (side == 'SELL' and tp >= sl):
        return {'outcome': 'INDETERMINATE', 'bars_checked': 0, 'exit_time_utc': None,
                'gross_pips_reference': None, 'detail': 'SL/TP invertidos'}
    if not candles:
        return {'outcome': 'INDETERMINATE', 'bars_checked': 0, 'exit_time_utc': None,
                'gross_pips_reference': None, 'detail': 'No hay velas futuras suficientes'}
    expected = int(datetime.fromisoformat(decision['decision_time_utc'].replace('Z', '+00:00')).timestamp())
    for i, c in enumerate(candles[:horizon], start=1):
        if c['candle_time'] != expected:
            return {'outcome': 'INDETERMINATE', 'bars_checked': i - 1, 'exit_time_utc': None,
                    'gross_pips_reference': None, 'detail': 'Hueco temporal en M5; no se infiere trayectoria'}
        expected += STEP
        lo, hi = c['low'], c['high']
        if not (math.isfinite(lo) and math.isfinite(hi) and lo <= hi):
            return {'outcome': 'INDETERMINATE', 'bars_checked': i, 'exit_time_utc': None,
                    'gross_pips_reference': None, 'detail': 'OHLC inválido'}
        hit_sl = lo <= sl if side == 'BUY' else hi >= sl
        hit_tp = hi >= tp if side == 'BUY' else lo <= tp
        when = datetime.fromtimestamp(c['candle_time'], timezone.utc).isoformat()
        if hit_sl and hit_tp:
            return {'outcome': 'INDETERMINATE', 'bars_checked': i, 'exit_time_utc': when,
                    'gross_pips_reference': None, 'detail': 'SL y TP tocados en la misma vela; orden desconocido'}
        if hit_sl or hit_tp:
            result = 'LOSS' if hit_sl else 'WIN'
            # Distancia entre niveles, no PnL ejecutable: sin precio de entrada bid/ask.
            return {'outcome': result, 'bars_checked': i, 'exit_time_utc': when,
                    'gross_pips_reference': None,
                    'detail': f'{"SL" if hit_sl else "TP"} tocado según OHLC; sin costos ni ejecución verificados'}
    return {'outcome': 'INDETERMINATE', 'bars_checked': min(len(candles), horizon),
            'exit_time_utc': None, 'gross_pips_reference': None,
            'detail': 'Ningún nivel tocado dentro del horizonte; no se fuerza un cierre'}


def main():
    p = argparse.ArgumentParser(description='Evalúa señales históricas; no envía órdenes')
    p.add_argument('--history', type=Path, default=HISTORY)
    p.add_argument('--journal', type=Path, default=JOURNAL)
    p.add_argument('--horizon-bars', type=int, default=48, help='48 velas = 4 horas M5')
    p.add_argument('--preview', action='store_true', help='Solo muestra; no escribe')
    p.add_argument('--all', action='store_true', help='Evalúa todas las decisiones no evaluadas')
    args = p.parse_args()
    if not 1 <= args.horizon_bars <= 2016:
        p.error('horizon-bars debe estar entre 1 y 2016')
    if not args.history.is_file() or not args.journal.is_file():
        p.error('Falta historical.sqlite3 o ai_decisions.sqlite3 en data/')
    with sqlite3.connect(f'file:{args.history.resolve().as_posix()}?mode=ro', uri=True) as hist, sqlite3.connect(args.journal) as journal:
        hist.row_factory = sqlite3.Row
        journal.row_factory = sqlite3.Row
        rows = journal.execute('SELECT * FROM ai_historical_decisions WHERE evaluation_status=? ORDER BY created_at_utc ASC', ('NOT_EVALUATED',)).fetchall()
        if not args.all:
            rows = rows[:1]
        if not rows:
            print('No hay decisiones pendientes de evaluación.')
            return
        if not args.preview:
            journal.execute('''CREATE TABLE IF NOT EXISTS ai_historical_evaluations (
                decision_id TEXT PRIMARY KEY, evaluated_at_utc TEXT NOT NULL,
                outcome TEXT NOT NULL, bars_checked INTEGER NOT NULL,
                exit_time_utc TEXT, gross_pips_reference REAL, detail TEXT NOT NULL,
                horizon_bars INTEGER NOT NULL, method TEXT NOT NULL)''')
        for row in rows:
            decision = dict(row)
            ts = int(datetime.fromisoformat(decision['decision_time_utc'].replace('Z', '+00:00')).timestamp())
            candles = [dict(c) for c in hist.execute('''SELECT candle_time,open,high,low,close
                FROM historical_candles WHERE symbol=? AND timeframe='M5' AND candle_time>=?
                ORDER BY candle_time LIMIT ?''', (decision['symbol'], ts, args.horizon_bars)).fetchall()]
            result = evaluate(decision, candles, args.horizon_bars)
            print(json.dumps({'decision_id': decision['decision_id'], 'decision': decision['decision'],
                              'decision_time_utc': decision['decision_time_utc'], **result,
                              'preview': args.preview, 'orders_sent': False}, ensure_ascii=False, indent=2))
            if not args.preview:
                journal.execute('''INSERT INTO ai_historical_evaluations
                    (decision_id,evaluated_at_utc,outcome,bars_checked,exit_time_utc,gross_pips_reference,detail,horizon_bars,method)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (decision['decision_id'], datetime.now(timezone.utc).isoformat(), result['outcome'],
                     result['bars_checked'], result['exit_time_utc'], result['gross_pips_reference'],
                     result['detail'], args.horizon_bars, 'M5_OHLC_LEVEL_TOUCH_V1'))
                journal.execute('UPDATE ai_historical_decisions SET evaluation_status=? WHERE decision_id=?',
                                (result['outcome'], decision['decision_id']))
        if not args.preview:
            journal.commit()
            print('Evaluaciones guardadas en:', args.journal)


if __name__ == '__main__':
    try:
        main()
    except (sqlite3.Error, ValueError, OSError) as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
