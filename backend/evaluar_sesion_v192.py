"""V1.9.2: evaluación OHLC conservadora con cierre obligatorio 10:00 Managua.
No modifica las evaluaciones V1.9.1 y jamás envía órdenes.
"""
import argparse
import json
import math
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo('America/Managua')
STEP = 300


def evaluate(decision, candles):
    side = decision['decision']
    if side == 'WAIT':
        return dict(outcome='WAIT', bars_checked=0, exit_time_utc=None, gross_pips_reference=None,
                    detail='Sin entrada hipotética')
    sl, tp = decision['stop_loss'], decision['take_profit']
    if side not in ('BUY', 'SELL') or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (sl, tp)):
        return dict(outcome='INDETERMINATE', bars_checked=0, exit_time_utc=None, gross_pips_reference=None, detail='SL/TP inválidos')
    asof = datetime.fromisoformat(decision['decision_time_utc'].replace('Z', '+00:00'))
    if asof.tzinfo is None:
        raise ValueError('decision_time_utc requiere zona UTC')
    asof = asof.astimezone(timezone.utc)
    local = asof.astimezone(TZ)
    end_local = datetime.combine(local.date(), time(10, 0), tzinfo=TZ)
    end_utc = end_local.astimezone(timezone.utc)
    if not (time(2, 0) <= local.time().replace(tzinfo=None) < time(10, 0)):
        return dict(outcome='INDETERMINATE', bars_checked=0, exit_time_utc=None, gross_pips_reference=None, detail='Entrada fuera de sesión')
    if (end_utc - asof).total_seconds() % STEP:
        raise ValueError('Fin de sesión no alineado con M5')
    max_bars = int((end_utc - asof).total_seconds() // STEP)
    entry = json.loads(decision['context_json'])['candles']['M5'][-1]['close']
    if not isinstance(entry, (int, float)) or not math.isfinite(entry):
        raise ValueError('Cierre de referencia inválido')
    if (side == 'BUY' and not (sl < entry < tp)) or (side == 'SELL' and not (tp < entry < sl)):
        return dict(outcome='INDETERMINATE', bars_checked=0, exit_time_utc=None, gross_pips_reference=None, detail='Niveles no rodean cierre de referencia')
    expected = int(asof.timestamp())
    for i in range(max_bars):
        if i >= len(candles) or candles[i]['candle_time'] != expected:
            return dict(outcome='INDETERMINATE', bars_checked=i, exit_time_utc=None, gross_pips_reference=None, detail='Faltan velas M5 continuas antes del cierre')
        c = candles[i]
        expected += STEP
        if any(not isinstance(c[k], (int, float)) or not math.isfinite(c[k]) for k in ('open', 'high', 'low', 'close')) or not (c['low'] <= c['open'] <= c['high'] and c['low'] <= c['close'] <= c['high']):
            return dict(outcome='INDETERMINATE', bars_checked=i+1, exit_time_utc=None, gross_pips_reference=None, detail='OHLC inválido')
        # La entrada al cierre previo es una referencia; si la primera apertura salta niveles, no se simula llenado.
        if i == 0 and (c['open'] <= min(sl, tp) or c['open'] >= max(sl, tp)):
            return dict(outcome='INDETERMINATE', bars_checked=1, exit_time_utc=None, gross_pips_reference=None, detail='Apertura fuera de SL/TP; ejecución desconocida')
        hit_sl = c['low'] <= sl if side == 'BUY' else c['high'] >= sl
        hit_tp = c['high'] >= tp if side == 'BUY' else c['low'] <= tp
        when = datetime.fromtimestamp(c['candle_time'] + STEP, timezone.utc).isoformat()
        if hit_sl and hit_tp:
            return dict(outcome='INDETERMINATE', bars_checked=i+1, exit_time_utc=when, gross_pips_reference=None, detail='SL y TP en misma vela; orden desconocido')
        if hit_sl or hit_tp:
            return dict(outcome='LOSS' if hit_sl else 'WIN', bars_checked=i+1, exit_time_utc=when,
                        gross_pips_reference=None, detail='Contacto OHLC con SL/TP; sin spread ni ejecución')
        if i == max_bars - 1:
            # Cierre hipotético al precio close de la última vela que termina a las 10:00.
            pips = (c['close'] - entry) / 0.0001 * (1 if side == 'BUY' else -1)
            return dict(outcome='SESSION_CLOSE', bars_checked=i+1, exit_time_utc=when,
                        gross_pips_reference=round(pips, 2), detail='Cierre de referencia 10:00 Managua; pips brutos sin costos, no WIN/LOSS')
    return dict(outcome='INDETERMINATE', bars_checked=0, exit_time_utc=None, gross_pips_reference=None, detail='Sin barras disponibles')


def main():
    p = argparse.ArgumentParser(description='Reevalúa decisiones hasta 10:00 Managua sin tocar V1.9.1')
    p.add_argument('--history', type=Path, default=ROOT / 'data' / 'historical.sqlite3')
    p.add_argument('--journal', type=Path, default=ROOT / 'data' / 'ai_decisions.sqlite3')
    p.add_argument('--preview', action='store_true')
    p.add_argument('--all', action='store_true')
    args = p.parse_args()
    if not args.history.is_file() or not args.journal.is_file():
        p.error('Falta historical.sqlite3 o ai_decisions.sqlite3; comprobá carpeta data')
    with sqlite3.connect(f'file:{args.history.resolve().as_posix()}?mode=ro', uri=True) as hist, sqlite3.connect(args.journal) as journal:
        hist.row_factory = sqlite3.Row
        journal.row_factory = sqlite3.Row
        decisions = journal.execute('SELECT * FROM ai_historical_decisions ORDER BY created_at_utc').fetchall()
        if not args.preview:
            journal.execute('''CREATE TABLE IF NOT EXISTS ai_session_evaluations_v192 (
                decision_id TEXT PRIMARY KEY, evaluated_at_utc TEXT NOT NULL,
                outcome TEXT NOT NULL, bars_checked INTEGER NOT NULL,
                exit_time_utc TEXT, gross_pips_reference REAL, detail TEXT NOT NULL,
                method TEXT NOT NULL)''')
        existing = {r[0] for r in journal.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_session_evaluations_v192'")}
        done = set()
        if existing:
            done = {r[0] for r in journal.execute('SELECT decision_id FROM ai_session_evaluations_v192')}
        pending = [d for d in decisions if d['decision_id'] not in done]
        if not args.all:
            pending = pending[:1]
        if not pending:
            print('No hay decisiones pendientes de evaluación de sesión.')
            return
        for row in pending:
            d = dict(row)
            ts = int(datetime.fromisoformat(d['decision_time_utc'].replace('Z', '+00:00')).timestamp())
            candles = [dict(c) for c in hist.execute('''SELECT candle_time,open,high,low,close FROM historical_candles
                WHERE symbol=? AND timeframe='M5' AND candle_time>=? ORDER BY candle_time LIMIT 100''', (d['symbol'], ts))]
            result = evaluate(d, candles)
            print(json.dumps({'decision_id': d['decision_id'], 'decision': d['decision'], 'decision_time_utc': d['decision_time_utc'],
                              **result, 'preview': args.preview, 'orders_sent': False}, ensure_ascii=False, indent=2))
            if not args.preview:
                journal.execute('''INSERT INTO ai_session_evaluations_v192 VALUES (?,?,?,?,?,?,?,?)''',
                                (d['decision_id'], datetime.now(timezone.utc).isoformat(), result['outcome'], result['bars_checked'],
                                 result['exit_time_utc'], result['gross_pips_reference'], result['detail'], 'M5_SESSION_CLOSE_1000_V192'))
        if not args.preview:
            journal.commit()
            print('Evaluación de sesión guardada en', args.journal)
            print('Se conservaron intactas las evaluaciones V1.9.1.')


if __name__ == '__main__':
    main()
