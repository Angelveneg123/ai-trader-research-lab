import sys
from contextlib import closing
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.prospective_store import connect, latest_market_cycles


def insert_cycle(db, cycle_id, symbol, hour, action=None, error=None):
    closed = f"2026-11-23T{hour}:00:00+00:00"
    with db:
        db.execute("""INSERT INTO prospective_cycles
            (cycle_id,created_utc,symbol,m5_closed_utc,context_sha256,context_json,spread_pips,session_allowed)
            VALUES (?,?,?,?,?,'{}',.8,1)""", (cycle_id, closed, symbol, closed, "fixture"))
        if action or error:
            db.execute("""INSERT INTO prospective_attempts
                (cycle_id,provider,local_day,started_utc,reserved_usd,status)
                VALUES (?,'gemini','2026-11-23',?,.01,?)""", (cycle_id, closed, "error" if error else "saved"))
        if action:
            db.execute("""INSERT INTO prospective_decisions
                (cycle_id,provider,model,received_utc,action,reason,raw_json,valid,risk_note)
                VALUES (?,'gemini','fixture',?,?,'fixture','{}',0,'observacion')""", (cycle_id, closed, action))
        if error:
            db.execute("""INSERT INTO prospective_errors (cycle_id,provider,occurred_utc,error)
                VALUES (?,'gemini',?,?)""", (cycle_id, closed, error))


def test_dashboard_returns_latest_cycle_for_each_market(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    path = tmp_path / "prospective.sqlite3"
    monkeypatch.setenv("PROSPECTIVE_DB", str(path))
    monkeypatch.setenv("MT5_SYMBOLS", "EURUSDmicro,USDJPYdemo")
    with closing(connect()) as db:
        insert_cycle(db, "eur-before", "EURUSDmicro", "10", action="WAIT")
        insert_cycle(db, "eur-latest", "EURUSDmicro", "11", error="HTTP 429")
        insert_cycle(db, "jpy-latest", "USDJPYdemo", "09", action="WAIT")

    response = TestClient(app).get("/api/prospective/markets")
    assert response.status_code == 200
    eur, jpy, gold = response.json()["markets"]
    assert eur["latest"]["cycle_id"] == "eur-latest"
    assert eur["latest"]["action"] is None
    assert eur["latest"]["error"] == "HTTP 429"
    assert jpy["symbol"] == "USDJPYdemo"
    assert jpy["latest"]["action"] == "WAIT"
    assert jpy["latest"]["spread_pips"] == pytest.approx(.8)
    assert gold == {"label": "XAU/USD", "symbol": "XAUUSDmicro", "latest": None}


def test_latest_cycle_handles_older_journal_and_missing_database(tmp_path, monkeypatch):
    path = tmp_path / "prospective.sqlite3"
    monkeypatch.setenv("PROSPECTIVE_DB", str(path))
    assert latest_market_cycles(("EURUSDmicro",)) == {"EURUSDmicro": None}
    assert not path.exists()

    with closing(connect()) as db:
        insert_cycle(db, "previous", "EURUSDmicro", "09", action="WAIT")
        with db:
            db.execute("DROP TABLE prospective_attempts")
    latest = latest_market_cycles(("EURUSDmicro",))["EURUSDmicro"]
    assert latest["cycle_id"] == "previous"
    assert latest["request_status"] == "saved"
