"""Local read models and authenticated controls for the lab."""
import csv
import hmac
import io
import os
from contextlib import closing

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, StrictBool

from .market_symbols import load_settings
from .prospective_store import connect, db_path, set_entries_blocked

router = APIRouter()


class EntryControl(BaseModel):
    blocked: StrictBool


def authenticate(authorization):
    load_settings()
    configured = os.getenv("LAB_CONTROL_TOKEN", "")
    if len(configured) < 24:
        raise HTTPException(503, "Configurá LAB_CONTROL_TOKEN con al menos 24 caracteres.")
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(value.encode(), configured.encode()):
        raise HTTPException(401, "Credencial de control inválida.", headers={"WWW-Authenticate": "Bearer"})


@router.post("/api/controls/entries")
def entry_control(body: EntryControl, authorization: str | None = Header(default=None)):
    authenticate(authorization)
    with closing(connect()) as db:
        set_entries_blocked(db, body.blocked)
    return {"blocked": body.blocked}


@router.get("/api/prospective/export")
def export(format: str = "json"):
    if format not in ("csv", "json"):
        raise HTTPException(400, "Formato esperado: csv o json")
    load_settings()
    fields = ["cycle_id", "symbol", "m5_closed_utc", "provider", "model", "received_utc",
              "action", "reason", "sl", "tp", "valid", "risk_note", "cost_usd_est", "outcome", "net_pips"]
    rows = []
    if db_path().is_file():
        with closing(connect(readonly=True)) as db:
            rows = [dict(r) for r in db.execute("""
                SELECT c.cycle_id,c.symbol,c.m5_closed_utc,d.provider,d.model,d.received_utc,
                       d.action,d.reason,d.sl,d.tp,d.valid,d.risk_note,d.cost_usd_est,o.outcome,o.net_pips
                FROM prospective_decisions d JOIN prospective_cycles c ON c.cycle_id=d.cycle_id
                LEFT JOIN prospective_outcomes o ON o.cycle_id=d.cycle_id AND o.provider=d.provider
                ORDER BY d.received_utc,d.provider
            """)]
    if format == "json":
        return rows
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([safe_csv(row[field]) for field in fields])
    return Response(out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="decisiones_prospectivas.csv"',
    })


def safe_csv(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
