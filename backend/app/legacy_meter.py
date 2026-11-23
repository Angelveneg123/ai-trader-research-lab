"""Route historical Gemini calls through the shared cumulative ledger."""
import math
import os
import uuid
from contextlib import closing

from .market_symbols import load_settings
from .prospective_store import CAP_USD, budget, connect, utc_now, write_lock


def generate_content(client, *, model, symbol="EURUSD", ceiling=.05, authorized=False, **options):
    from prospectivo_v22 import provider_price

    load_settings()
    if not authorized and os.getenv("LAB_LEGACY_API_COST") != "1":
        raise RuntimeError("La consulta histórica requiere LAB_LEGACY_API_COST=1.")
    if not math.isfinite(ceiling) or not 0 < ceiling <= CAP_USD:
        raise ValueError("Reserva histórica inválida")
    request_id = "historical-" + uuid.uuid4().hex
    prices = provider_price("gemini", model)
    # Existing legacy commands select the per-call ceiling. Keep that reservation for unknown outcomes.
    with closing(connect()) as db:
        with write_lock(db):
            if ceiling > budget(db)["gemini"]["remaining"] + 1e-10:
                raise RuntimeError("Presupuesto acumulado insuficiente para Gemini.")
            db.execute("""
                INSERT INTO diagnostic_calls (diagnostic_id,provider,symbol,model,started_utc,reserved_usd,status)
                VALUES (?,'gemini',?,?,?,?, 'HISTORICAL_RESERVED')
            """, (request_id, symbol, model, utc_now().isoformat(), ceiling))
        try:
            response = client.models.generate_content(model=model, **options)
        except Exception as exc:
            with db:
                db.execute("UPDATE diagnostic_calls SET status='HISTORICAL_ERROR',error=? WHERE diagnostic_id=?",
                           (type(exc).__name__, request_id))
            raise RuntimeError("La consulta histórica falló. La reserva queda pendiente.") from None
        usage = getattr(response, "usage_metadata", None)
        tokens_in = getattr(usage, "prompt_token_count", None)
        out = getattr(usage, "candidates_token_count", None)
        thoughts = getattr(usage, "thoughts_token_count", None)
        tokens_out = out + (thoughts or 0) if type(out) is int and type(thoughts or 0) is int else None
        cost = ((tokens_in * prices[0] + tokens_out * prices[1])/1e6
                if prices and all(type(n) is int and n >= 0 for n in (tokens_in, tokens_out)) else None)
        with db:
            db.execute("""UPDATE diagnostic_calls SET received_utc=?,cost_usd_est=?,status='HISTORICAL_ONLY'
                          WHERE diagnostic_id=?""", (utc_now().isoformat(), cost, request_id))
        return response
