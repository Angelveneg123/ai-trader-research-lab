"""Motor de investigación observacional. No contiene llamadas de ejecución de órdenes."""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from .mt5_market import closed_candles, quote_in_session, read_session
from .market_symbols import live_symbols, valid_market_symbol
from . import audit_v16

DB = Path(os.getenv('RESEARCH_DB', str(Path(__file__).resolve().parents[2] / 'data' / 'research.sqlite3')))
DB.parent.mkdir(parents=True, exist_ok=True)
POLL_SECONDS = 15
_state_lock = threading.Lock()
_state = {'running': False, 'last_poll': None, 'last_error': None, 'errors': {}}


def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('''CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        candle_time INTEGER NOT NULL,
        observed_at TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        context_json TEXT NOT NULL,
        UNIQUE(symbol, candle_time)
    )''')
    audit_v16.init(db)
    db.commit()
    return db


def ema(values, period):
    if len(values) < period:
        return None
    result = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result
    return result


def compute_context(symbol, m5, m15, h1):
    # Cada timeframe contiene únicamente velas cerradas ANTES del cierre M5 analizado.
    closes_h1 = [x['close'] for x in h1]
    e20, e50 = ema(closes_h1, 20), ema(closes_h1, 50)
    trend = 'INSUFICIENTE'
    if e20 is not None and e50 is not None:
        trend = 'ALCISTA' if e20 > e50 and closes_h1[-1] > e20 else 'BAJISTA' if e20 < e50 and closes_h1[-1] < e20 else 'MIXTA'
    structure = 'INSUFICIENTE'
    if len(m15) >= 11:
        previous = m15[-11:-1]
        close = m15[-1]['close']
        structure = 'RUPTURA_ALCISTA' if close > max(x['high'] for x in previous) else 'RUPTURA_BAJISTA' if close < min(x['low'] for x in previous) else 'RANGO'
    current = m5[-1]
    body = abs(current['close'] - current['open'])
    spread = max(current['high'] - current['low'], 1e-12)
    direction = 'ALCISTA' if current['close'] > current['open'] else 'BAJISTA' if current['close'] < current['open'] else 'NEUTRA'
    context = {
        'symbol': symbol, 'candle_time': current['time'], 'candle_close_time': current['time'] + 300,
        'h1': {'trend': trend, 'ema20': e20, 'ema50': e50, 'last_closed_time': h1[-1]['time'] if h1 else None},
        'm15': {'structure': structure, 'last_closed_time': m15[-1]['time'] if m15 else None},
        'm5': {'direction': direction, 'body_ratio': round(body / spread, 4), 'close': current['close'], 'volume': current['volume']},
        'data_counts': {'h1': len(h1), 'm15': len(m15), 'm5': len(m5)},
        'model': 'deterministic_observer_v1', 'orders_enabled': False
    }
    aligned = (trend == 'ALCISTA' and structure == 'RUPTURA_ALCISTA' and direction == 'ALCISTA') or (trend == 'BAJISTA' and structure == 'RUPTURA_BAJISTA' and direction == 'BAJISTA')
    decision = 'OBSERVAR' if aligned and body / spread >= 0.5 else 'ESPERAR'
    reason = 'Coincidencia H1/M15/M5 observada; NO es señal operable' if decision == 'OBSERVAR' else 'Sin coincidencia multitemporal suficiente o datos incompletos'
    return decision, reason, context


def analyze_symbol(symbol):
    # Use the same MT5 session for all timeframes of this symbol.
    with read_session() as mt5:
        m5 = closed_candles(mt5, symbol, 'M5', 100)
        latest = m5[-1]
        with connect() as db:
            exists = db.execute('SELECT 1 FROM observations WHERE symbol=? AND candle_time=?', (symbol, latest['time'])).fetchone()
            audited = db.execute('SELECT 1 FROM audit_v16 WHERE symbol=? AND candle_time=?', (symbol, latest['time'])).fetchone()
            if exists and audited:
                audit_v16.update_outcomes(db, symbol, m5)
                return False
        cutoff = latest['time'] + 300
        h1 = closed_candles(mt5, symbol, 'H1', 250, cutoff)
        m15 = closed_candles(mt5, symbol, 'M15', 100, cutoff)
        quote = quote_in_session(mt5, symbol)
    decision, reason, context = compute_context(symbol, m5, m15, h1)
    v16_decision, v16_reason, v16_context = audit_v16.build(symbol, m5, m15, h1, quote=quote)
    with connect() as db:
        audit_v16.insert(db, symbol, v16_decision, v16_reason, v16_context)
        audit_v16.update_outcomes(db, symbol, m5)
        result = db.execute('INSERT OR IGNORE INTO observations (symbol,candle_time,observed_at,decision,reason,context_json) VALUES (?,?,?,?,?,?)', (symbol, latest['time'], datetime.now(timezone.utc).isoformat(), decision, reason, json.dumps(context)))
        db.commit()
        return result.rowcount > 0


def poll_once():
    errors = {}
    for symbol in live_symbols():
        try:
            analyze_symbol(symbol)
        except Exception as exc:
            errors[symbol] = str(exc)
    with _state_lock:
        _state['last_poll'] = datetime.now(timezone.utc).isoformat()
        _state['errors'] = errors
        _state['last_error'] = '; '.join(f'{k}: {v}' for k, v in errors.items()) if errors else None
    return errors


def worker(stop):
    with _state_lock:
        _state['running'] = True
    try:
        while not stop.is_set():
            poll_once()
            stop.wait(POLL_SECONDS)
    finally:
        with _state_lock:
            _state['running'] = False


def start_worker():
    connect().close()
    stop = threading.Event()
    thread = threading.Thread(target=worker, args=(stop,), name='research-observer', daemon=True)
    thread.start()
    return stop, thread


def get_observations(symbol=None, limit=50):
    if symbol and not valid_market_symbol(symbol):
        raise ValueError('Símbolo no permitido')
    with connect() as db:
        if symbol:
            rows = db.execute('SELECT * FROM observations WHERE symbol=? ORDER BY candle_time DESC LIMIT ?', (symbol, limit)).fetchall()
        else:
            rows = db.execute('SELECT * FROM observations ORDER BY candle_time DESC LIMIT ?', (limit,)).fetchall()
    return [{**dict(row), 'context': json.loads(row['context_json'])} for row in rows]


def get_status():
    with _state_lock:
        state = dict(_state)
        state['errors'] = dict(_state['errors'])
    with connect() as db:
        legacy_total = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        audit_total = db.execute('SELECT COUNT(*) FROM audit_v16').fetchone()[0]
        outcomes_total = db.execute('SELECT COUNT(*) FROM outcomes_v16').fetchone()[0]
    return {**state, 'total_observations': legacy_total, 'total_audits': audit_total, 'total_outcomes': outcomes_total, 'storage': 'sqlite', 'ai_connected': False, 'orders_enabled': False, 'poll_seconds': POLL_SECONDS}


def get_audit(symbol=None, limit=50):
    if symbol and not valid_market_symbol(symbol):
        raise ValueError('Símbolo no permitido')
    with connect() as db:
        return audit_v16.list_audit(db,symbol,limit)

def get_metrics():
    with connect() as db:
        return audit_v16.metrics(db)
