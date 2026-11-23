"""Read-only research status. No provider calls and no trading operations."""
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / 'data' / 'ai_decisions.sqlite3'
ENV_PATH = ROOT / 'backend' / '.env'

def _table_exists(db, name):
    return db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (name,)).fetchone() is not None

def snapshot(symbol='EURUSD'):
    load_dotenv(ENV_PATH, override=False)
    configured = bool(os.getenv('GEMINI_API_KEY', '').strip())
    result = {'gemini': {'configured': configured, 'last_success': None, 'availability': 'not_checked', 'model': None},
              'openai': {'configured': bool(os.getenv('OPENAI_API_KEY', '').strip()), 'last_success': None, 'availability': 'not_checked'},
              'journal_available': False, 'total_decisions': 0, 'latest': None, 'budget': {'limit_usd': 2.5, 'spent_usd': None, 'source': 'not_tracked'}}
    if not DB_PATH.is_file():
        return result
    try:
        with sqlite3.connect(f'file:{DB_PATH.resolve().as_posix()}?mode=ro', uri=True, timeout=2) as db:
            db.row_factory = sqlite3.Row
            if not _table_exists(db, 'ai_historical_decisions'):
                return result
            result['journal_available'] = True
            result['total_decisions'] = db.execute('SELECT COUNT(*) FROM ai_historical_decisions').fetchone()[0]
            row = db.execute('''SELECT decision_id,created_at_utc,decision_time_utc,symbol,model,decision,confidence,reason,stop_loss,take_profit
                                FROM ai_historical_decisions WHERE symbol=? ORDER BY created_at_utc DESC, rowid DESC LIMIT 1''', (symbol,)).fetchone()
            last = db.execute('SELECT created_at_utc,model FROM ai_historical_decisions ORDER BY created_at_utc DESC LIMIT 1').fetchone()
            if last:
                result['gemini']['last_success'] = last['created_at_utc']
                result['gemini']['model'] = last['model']
            if row:
                result['latest'] = dict(row)
                for table in ('ai_session_evaluations_v192',):
                    if _table_exists(db, table):
                        cols = {r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                        if {'decision_id','outcome'}.issubset(cols):
                            ev = db.execute(f'SELECT outcome FROM {table} WHERE decision_id=? LIMIT 1', (row['decision_id'],)).fetchone()
                            if ev: result['latest']['outcome'] = ev['outcome']
    except (sqlite3.Error, OSError) as exc:
        result['journal_error'] = type(exc).__name__
    return result
