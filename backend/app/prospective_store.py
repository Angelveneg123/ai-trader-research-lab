"""SQLite journal shared by the prospective runner and the dashboard."""
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .market_symbols import settings_path

UTC = timezone.utc
LOCAL = ZoneInfo("America/Managua")
CAP_USD = 2.5
DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "prospective_v22.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_status (
 id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL, provider TEXT NOT NULL, checked_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entry_control (
 id INTEGER PRIMARY KEY CHECK(id=1), blocked INTEGER NOT NULL CHECK(blocked IN (0,1)), changed_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entry_control_audit (
 id INTEGER PRIMARY KEY, blocked INTEGER NOT NULL, changed_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS demo_management (
 cycle_id TEXT PRIMARY KEY, account INTEGER NOT NULL, position_id INTEGER NOT NULL,
 action TEXT NOT NULL, status TEXT NOT NULL, started_utc TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS demo_metrics (
 id INTEGER PRIMARY KEY CHECK(id=1), equity REAL NOT NULL, daily_drawdown_usd REAL NOT NULL,
 peak_pnl_usd REAL NOT NULL, local_day TEXT NOT NULL, positions_json TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS diagnostic_calls (
 diagnostic_id TEXT NOT NULL, provider TEXT NOT NULL, symbol TEXT NOT NULL,
 model TEXT NOT NULL, started_utc TEXT NOT NULL, received_utc TEXT,
 reserved_usd REAL NOT NULL, cost_usd_est REAL, status TEXT NOT NULL,
 action TEXT, reason TEXT, error TEXT, PRIMARY KEY(diagnostic_id,provider));
CREATE TABLE IF NOT EXISTS prospective_cycles (
 cycle_id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, symbol TEXT NOT NULL,
 m5_closed_utc TEXT NOT NULL, context_sha256 TEXT NOT NULL, context_json TEXT NOT NULL,
 spread_pips REAL, session_allowed INTEGER NOT NULL, UNIQUE(symbol,m5_closed_utc));
CREATE TABLE IF NOT EXISTS prospective_decisions (
 cycle_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 received_utc TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
 sl REAL, tp REAL, raw_json TEXT NOT NULL, valid INTEGER NOT NULL,
 risk_note TEXT NOT NULL, cost_usd_est REAL NOT NULL DEFAULT 0,
 PRIMARY KEY(cycle_id,provider));
CREATE TABLE IF NOT EXISTS prospective_errors (
 id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT, provider TEXT,
 occurred_utc TEXT NOT NULL, error TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prospective_attempts (
 cycle_id TEXT NOT NULL, provider TEXT NOT NULL, local_day TEXT NOT NULL,
 started_utc TEXT NOT NULL, reserved_usd REAL NOT NULL, cost_usd_est REAL,
 status TEXT NOT NULL, PRIMARY KEY(cycle_id,provider));
CREATE INDEX IF NOT EXISTS prospective_attempt_day ON prospective_attempts(local_day,provider);
CREATE TABLE IF NOT EXISTS prospective_outcomes (
 cycle_id TEXT NOT NULL, provider TEXT NOT NULL, outcome TEXT NOT NULL,
 evaluated_utc TEXT NOT NULL, entry_utc TEXT, exit_utc TEXT,
 entry_price REAL, exit_price REAL, net_pips REAL, cost_pips REAL, detail TEXT NOT NULL,
 PRIMARY KEY(cycle_id,provider));
CREATE TABLE IF NOT EXISTS prospective_demo_entries (
 cycle_id TEXT PRIMARY KEY, account INTEGER NOT NULL, symbol TEXT NOT NULL,
 order_comment TEXT NOT NULL, status TEXT NOT NULL, updated_utc TEXT NOT NULL,
 position_id INTEGER, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prospective_demo_days (
 account INTEGER NOT NULL, local_day TEXT NOT NULL, loss_blocked INTEGER NOT NULL,
 PRIMARY KEY(account,local_day));
CREATE TABLE IF NOT EXISTS prospective_demo_positions (
 account INTEGER NOT NULL, position_id INTEGER NOT NULL, expires_utc TEXT NOT NULL,
 PRIMARY KEY(account,position_id));
CREATE TABLE IF NOT EXISTS prospective_demo_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_utc TEXT NOT NULL,
 account INTEGER NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS prospective_demo_deals (
 account INTEGER NOT NULL, ticket INTEGER NOT NULL, position_id INTEGER NOT NULL,
 local_day TEXT NOT NULL, happened_utc TEXT NOT NULL, symbol TEXT NOT NULL, entry INTEGER NOT NULL,
 reason INTEGER NOT NULL, volume REAL NOT NULL, price REAL NOT NULL, net_usd REAL NOT NULL,
 PRIMARY KEY(account,ticket));
CREATE TABLE IF NOT EXISTS prospective_demo_status (
 id INTEGER PRIMARY KEY CHECK(id=1), updated_utc TEXT NOT NULL, balance_usd REAL NOT NULL,
 local_day TEXT NOT NULL, realized_usd REAL NOT NULL, floating_usd REAL NOT NULL,
 positions INTEGER NOT NULL, loss_blocked INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS prospective_reports (
 local_day TEXT PRIMARY KEY, created_utc TEXT NOT NULL, body TEXT NOT NULL,
 telegram_status TEXT NOT NULL);
"""


def utc_now():
    return datetime.now(UTC)


def in_session(now):
    local = now.astimezone(LOCAL)
    return local.weekday() < 5 and 2 <= local.hour < 10


def session_end(now):
    day = now.astimezone(LOCAL).date()
    return datetime.combine(day, time(10), LOCAL).astimezone(UTC)


def db_path():
    return settings_path(os.getenv("PROSPECTIVE_DB") or DEFAULT_DB).resolve()


def connect(path=None, readonly=False):
    path = Path(path or db_path()).resolve()
    if readonly:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=20)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    return db


@contextmanager
def write_lock(db):
    db.execute("BEGIN IMMEDIATE")
    with db:
        yield


def initial_budget():
    return {p: {"limit": CAP_USD, "attempts": 0, "spent": 0.0, "reserved": 0.0, "remaining": CAP_USD}
            for p in ("gemini", "openai")}


def budget(db, day=None):
    """Cumulative charges in this journal. A date only filters reporting."""
    totals = initial_budget()
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    sources = []
    if "prospective_attempts" in tables:
        sources.append(("prospective_attempts", "local_day=?", (day,)))
    if "diagnostic_calls" in tables:
        start = datetime.combine(date.fromisoformat(day), time.min, LOCAL).astimezone(UTC) if day else None
        since = (start.isoformat(), (start + timedelta(days=1)).isoformat()) if day else ()
        sources.append(("diagnostic_calls", "started_utc>=? AND started_utc<?", since))
    for table, clause, args in sources:
        where = "WHERE " + clause if day is not None else ""
        rows = db.execute(f"""
            SELECT provider, COUNT(*) AS attempts, SUM(COALESCE(cost_usd_est,0)) AS spent,
                   SUM(CASE WHEN cost_usd_est IS NULL THEN reserved_usd ELSE 0 END) AS reserved
            FROM {table} {where} GROUP BY provider
        """, args if day else ())
        for row in rows:
            if row["provider"] in totals:
                for field in ("attempts", "spent", "reserved"):
                    totals[row["provider"]][field] += row[field]
    if not day and "provider_budget" in tables:
        for row in db.execute("SELECT provider,spent_usd,reserved_usd FROM provider_budget"):
            if row["provider"] in totals:
                totals[row["provider"]]["spent"] += row["spent_usd"]
                totals[row["provider"]]["reserved"] += row["reserved_usd"]
    for row in totals.values():
        row["remaining"] = max(0.0, CAP_USD - row["spent"] - row["reserved"])
    return totals


def entries_blocked(db):
    row = db.execute("SELECT blocked FROM entry_control WHERE id=1").fetchone()
    return bool(row and row[0])


def set_entries_blocked(db, blocked):
    with write_lock(db):
        now = utc_now().isoformat()
        db.execute("INSERT OR REPLACE INTO entry_control VALUES (1,?,?)", (int(blocked), now))
        db.execute("INSERT INTO entry_control_audit (blocked,changed_utc) VALUES (?,?)", (int(blocked), now))


def update_runtime(db, mode, provider):
    with db:
        db.execute("INSERT OR REPLACE INTO runtime_status VALUES (1,?,?,?)",
                   (mode, provider, utc_now().isoformat()))


def claim(db, cycle_id, provider, now, reserve):
    day = now.astimezone(LOCAL).date().isoformat()
    with write_lock(db):
        if db.execute("""
            SELECT 1 FROM prospective_attempts WHERE cycle_id=? AND provider=?
            UNION ALL SELECT 1 FROM prospective_decisions WHERE cycle_id=? AND provider=?
            UNION ALL SELECT 1 FROM prospective_errors WHERE cycle_id=? AND provider=?
        """, (cycle_id, provider) * 3).fetchone():
            return "ya procesado"
        current = budget(db)[provider]
        if reserve > current["remaining"] + 1e-10:
            return "presupuesto acumulado insuficiente"
        db.execute("""
            INSERT INTO prospective_attempts
            (cycle_id,provider,local_day,started_utc,reserved_usd,status)
            VALUES (?,?,?,?,?,'reserved')
        """, (cycle_id, provider, day, now.isoformat(), reserve))
    return "reserved"


def latest_market_cycles(symbols, provider="gemini"):
    """Return the newest stored candle and its decision, independently for each market."""
    results = dict.fromkeys(symbols)
    if not db_path().is_file():
        return results
    with closing(connect(readonly=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "prospective_cycles" not in tables:
            return results
        # Journals from before V2.3 have decisions but no separate attempts table.
        has_attempts = "prospective_attempts" in tables
        attempt_fields = "a.status AS request_status, a.cost_usd_est" if has_attempts else (
            "CASE WHEN d.action IS NOT NULL THEN 'saved' END AS request_status, d.cost_usd_est")
        attempts_join = """LEFT JOIN prospective_attempts a ON a.cycle_id=c.cycle_id
                           AND a.provider=?""" if has_attempts else ""
        params = (provider, provider, provider) if has_attempts else (provider, provider)
        for symbol in results:
            row = db.execute(f"""
                SELECT c.cycle_id, c.m5_closed_utc, c.spread_pips, d.action, d.reason,
                       d.received_utc, d.model, {attempt_fields},
                       (SELECT error FROM prospective_errors e WHERE e.cycle_id=c.cycle_id
                        AND e.provider=? ORDER BY e.id DESC LIMIT 1) AS error
                FROM prospective_cycles c
                LEFT JOIN prospective_decisions d ON d.cycle_id=c.cycle_id AND d.provider=?
                {attempts_join}
                WHERE c.symbol=?
                ORDER BY c.m5_closed_utc DESC LIMIT 1
            """, (*params, symbol)).fetchone()
            if row:
                results[symbol] = dict(row)
    return results


def snapshot(symbol=None, limit=30):
    empty = {
        "cycles": 0, "decisions": 0, "recent": [], "reports": [], "demo": None, "demo_events": [], "demo_deals": [],
        "budget": initial_budget(), "runtime": None, "entries_blocked": None, "metrics": None,
        "openai_enabled": os.getenv("OPENAI_ENABLED") == "1",
        "configured": {p: bool(os.getenv(p.upper() + "_API_KEY")) for p in ("gemini", "openai")},
    }
    try:
        with closing(connect(readonly=True)) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "prospective_attempts" not in tables:
                return {**empty, "budget": budget(db), "cycles": db.execute("SELECT COUNT(*) FROM prospective_cycles").fetchone()[0],
                        "decisions": db.execute("SELECT COUNT(*) FROM prospective_decisions").fetchone()[0]}
            rows = db.execute("""
                SELECT c.cycle_id,c.symbol, c.m5_closed_utc, c.spread_pips, a.provider,
                       a.status AS request_status, a.started_utc, a.cost_usd_est, d.model,
                       d.received_utc, d.action, d.reason, d.sl, d.tp, d.risk_note, o.outcome,
                       CASE WHEN json_valid(d.raw_json) THEN json_extract(d.raw_json,'$.tokens') END AS tokens,
                       CASE WHEN json_valid(d.raw_json) THEN json_extract(d.raw_json,'$.latency_ms') END AS latency_ms,
                       o.net_pips, o.cost_pips, o.detail AS outcome_detail,
                       (SELECT error FROM prospective_errors e WHERE e.cycle_id=c.cycle_id
                        AND e.provider=a.provider ORDER BY e.id DESC LIMIT 1) AS error
                FROM prospective_attempts a JOIN prospective_cycles c ON a.cycle_id=c.cycle_id
                LEFT JOIN prospective_decisions d ON d.cycle_id=a.cycle_id AND d.provider=a.provider
                LEFT JOIN prospective_outcomes o ON o.cycle_id=a.cycle_id AND o.provider=a.provider
                WHERE (? IS NULL OR c.symbol=?) ORDER BY a.started_utc DESC LIMIT ?
            """, (symbol, symbol, limit)).fetchall()
            return {
                **empty, "cycles": db.execute("SELECT COUNT(*) FROM prospective_cycles").fetchone()[0],
                "decisions": db.execute("SELECT COUNT(*) FROM prospective_decisions").fetchone()[0],
                "recent": [dict(r) for r in rows], "budget": budget(db),
                "runtime": dict(state) if "runtime_status" in tables and (state := db.execute("SELECT * FROM runtime_status").fetchone()) else None,
                "entries_blocked": entries_blocked(db) if "entry_control" in tables else None,
                "metrics": {**dict(metrics), "positions": json.loads(metrics["positions_json"])}
                           if "demo_metrics" in tables and (metrics := db.execute("SELECT * FROM demo_metrics").fetchone())
                           else None,
                "reports": [dict(r) for r in db.execute(
                    "SELECT * FROM prospective_reports ORDER BY local_day DESC LIMIT 14")],
                "demo": dict(demo) if (demo := db.execute("SELECT * FROM prospective_demo_status").fetchone()) else None,
                "demo_events": [dict(r) for r in db.execute(
                    "SELECT recorded_utc,symbol,kind,detail FROM prospective_demo_events ORDER BY id DESC LIMIT 15")],
                "demo_deals": [dict(r) for r in db.execute("""
                    SELECT ticket,happened_utc,symbol,entry,reason,volume,price,net_usd
                    FROM prospective_demo_deals ORDER BY happened_utc DESC,ticket DESC LIMIT 30
                """)],
            }
    except sqlite3.Error:
        return empty
