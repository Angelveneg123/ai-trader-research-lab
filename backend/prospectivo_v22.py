"""Prospective research runner. Observation by default, demo execution by opt-in."""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing, nullcontext
from datetime import date, datetime, timedelta

from app.market_symbols import live_symbols, load_settings, valid_market_symbol
from app.prospective_store import (
    CAP_USD, LOCAL, UTC, budget, claim, connect, db_path, in_session, session_end, utc_now, update_runtime,
)

TIMEFRAMES = {"M5": 300, "M15": 900, "H1": 3600}
OUTPUT_TOKENS = 600
REQUEST_TIMEOUT = 20
PRICES = {
    ("gemini", "gemini-3.1-flash-lite"): (0.25, 1.50),
    ("gemini", "gemini-2.5-flash"): (0.30, 2.50),
    ("openai", "gpt-4.1-mini"): (0.40, 1.60),
    ("openai", "gpt-5-mini"): (0.25, 2.00),
    ("openai", "gpt-5.4-mini"): (0.75, 4.50),
}
PROMPT_VERSION = "v2.5"
SYSTEM = (
    "Usa solo las cotizaciones y velas cerradas provistas. H1 da tendencia, M15 estructura y M5 oportunidad. "
    "Considera spread, volatilidad y posición actual. Devuelve un objeto JSON con action, reason, hypothesis, "
    "invalidation, horizon_m5, sl y tp. Acciones sin posición: BUY, SELL o WAIT. Con posición: HOLD, MODIFY o CLOSE. "
    "WAIT ante datos insuficientes. Para BUY, SELL o MODIFY, exige precios sl y tp, hypothesis e invalidation "
    "y horizon_m5 entero entre 1 y 96. Para WAIT, HOLD o CLOSE, sl y tp son null. "
    "Sé breve, escribe en español y usa los datos provistos. DIAGNOSTIC_ONLY permite solo BUY, SELL o WAIT."
)


def ema(prices, period):
    value = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        value += (price - value) * multiplier
    return value


def collect(symbol, diagnostic=False):
    from app.mt5_connection import connection

    with connection() as (mt5, _, _):
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Símbolo no disponible en el terminal: {symbol}")
        info = mt5.symbol_info(symbol)
        if not info or info.point <= 0:
            raise RuntimeError("Especificaciones del símbolo incompletas")

        now = utc_now()
        now_s = int(now.timestamp())
        close_s = now_s // TIMEFRAMES["M5"] * TIMEFRAMES["M5"]
        # Diagnostic snapshots may be historical, but must be internally time-aligned.
        if diagnostic:
            m5_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 3)
            m5_closed = sorted((r for r in (m5_rates if m5_rates is not None else [])
                                if int(r["time"]) + 300 <= close_s),
                               key=lambda r: int(r["time"]))
            if not m5_closed:
                raise RuntimeError("No hay ninguna vela M5 cerrada disponible")
            close_s = int(m5_closed[-1]["time"]) + 300
        candles = {}
        indicators = {}
        for tf, seconds in TIMEFRAMES.items():
            size = 110 if tf == "H1" else 24
            rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, f"TIMEFRAME_{tf}"), 0, size)
            closed = [] if rates is None else sorted(
                (r for r in rates if int(r["time"]) + seconds <= close_s),
                key=lambda r: int(r["time"]),
            )
            if len(closed) < (50 if tf == "H1" else 20):
                raise RuntimeError(f"Calentamiento insuficiente en {tf}")
            if not diagnostic and int(closed[-1]["time"]) + seconds != close_s // seconds * seconds:
                raise RuntimeError(f"La última vela cerrada de {tf} aún no está disponible")
            candles[tf] = []
            for r in closed[-20:]:
                o, h, low, c = (float(r[k]) for k in ("open", "high", "low", "close"))
                if not all(math.isfinite(p) for p in (o, h, low, c)) or not 0 < low <= min(o, c) <= max(o, c) <= h:
                    raise RuntimeError(f"OHLC inválido en {tf}")
                candles[tf].append({"t": int(r["time"]), "o": o, "h": h, "l": low, "c": c, "v": int(r["tick_volume"])})
            if tf == "H1":
                prices = [float(r["close"]) for r in closed]
                if any(not math.isfinite(p) or p <= 0 for p in prices):
                    raise RuntimeError("Precios inválidos en el calentamiento H1")
                indicators = {f"ema{p}": round(ema(prices, p), info.digits) for p in (20, 50)}

        tick = mt5.symbol_info_tick(symbol)
        quote_time = int(tick.time) if tick else 0
        age = int(utc_now().timestamp()) - quote_time
        if not tick or not all(math.isfinite(p) for p in (tick.bid, tick.ask)) or not 0 < tick.bid <= tick.ask or (not diagnostic and not -5 <= age <= 120):
            raise RuntimeError("Cotización MT5 inválida u obsoleta")
        pip = info.point * (10 if info.digits in (3, 5) else 1)
        position = None
        if not diagnostic:
            from app.demo_execution import MAGIC
            positions = mt5.positions_get(symbol=symbol)
            if positions is None:
                raise RuntimeError("No se pudieron verificar las posiciones de MT5")
            owned = [p for p in positions if p.magic == MAGIC]
            if len(owned) > 1:
                raise RuntimeError("Hay más de una posición del laboratorio en el símbolo")
            if owned:
                p = owned[0]
                position = {"identifier": p.identifier, "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                            "sl": p.sl, "tp": p.tp, "price_open": p.price_open}
        m5 = candles["M5"][-15:]
        atr = sum(max(bar["h"] - bar["l"], abs(bar["h"] - previous["c"]), abs(bar["l"] - previous["c"]))
                  for previous, bar in zip(m5, m5[1:])) / 14
        return {
            "position": position, "atr_m5": atr,
            "symbol": symbol, "candles": candles, "h1_indicators": indicators,
            "diagnostic_only": bool(diagnostic), "historical_snapshot": bool(diagnostic),
            "snapshot_age_seconds": max(0, now_s - close_s),
            "m5_closed_utc": datetime.fromtimestamp(close_s, UTC).isoformat(),
            "captured_utc": now.isoformat(), "quote_utc": datetime.fromtimestamp(quote_time, UTC).isoformat(),
            "bid": float(tick.bid), "ask": float(tick.ask), "spread_pips": (tick.ask - tick.bid) / pip,
            "digits": info.digits, "point": info.point, "pip_size": pip,
            "trade_stops_level": info.trade_stops_level, "contract_size": info.trade_contract_size,
            "quote_currency": info.currency_profit, "reference_price": candles["M5"][-1]["c"],
        }


def request_json(url, headers, payload, timeout=REQUEST_TIMEOUT):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Preserve the provider's actionable error, without logging credentials.
        try:
            body = exc.read(8192).decode("utf-8", errors="replace")
            parsed = json.loads(body)
            error = parsed.get("error", {}) if isinstance(parsed, dict) else {}
            detail = error.get("message", "")
            status = error.get("status", "")
        except (ValueError, TypeError, AttributeError):
            detail, status = "", ""
        detail = " ".join(str(detail).split())[:350]
        # Do not leak keys if a service includes one in its error response.
        for secret in (headers.get("x-goog-api-key"), headers.get("Authorization")):
            if secret:
                detail = detail.replace(secret, "[REDACTED]")
        raise RuntimeError(f"HTTP {exc.code} {status}: {detail}".strip()) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Conexión agotada o no disponible") from None


def parse_decision(raw, *, strict=False, diagnostic=False):
    if isinstance(raw, str):
        raw = json.loads(raw)
    allowed = ("BUY", "SELL", "WAIT") if diagnostic else ("BUY", "SELL", "WAIT", "HOLD", "MODIFY", "CLOSE")
    if not isinstance(raw, dict) or raw.get("action") not in allowed:
        raise ValueError("Acción inválida")
    action = raw["action"]
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Motivo vacío")
    sl, tp = raw.get("sl"), raw.get("tp")
    if action in ("WAIT", "HOLD", "CLOSE"):
        if sl is not None or tp is not None:
            raise ValueError(f"{action} requiere SL y TP vacíos")
        return action, reason.strip()[:1200], None, None
    if strict:
        horizon = raw.get("horizon_m5")
        if type(horizon) is not int or not 1 <= horizon <= 96:
            raise ValueError("Horizonte M5 inválido")
        for field in ("hypothesis", "invalidation"):
            value = raw.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 1200:
                raise ValueError(f"Campo de propuesta inválido: {field}")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (sl, tp)):
        raise ValueError("BUY/SELL requiere SL y TP finitos y positivos")
    return action, reason.strip()[:1200], float(sl), float(tp)


def provider_price(provider, model):
    prefix = provider.upper()
    input_price = os.getenv(f"{prefix}_INPUT_USD_PER_MTOK")
    output_price = os.getenv(f"{prefix}_OUTPUT_USD_PER_MTOK")
    if not input_price and not output_price:
        return PRICES.get((provider, model))
    prices = (float(input_price or "nan"), float(output_price or "nan"))
    if any(not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError(f"Configurá ambos precios de tokens de {provider}")
    return prices


def api_payload(ctx):
    position = ctx.get("position")
    visible = {k: v for k, v in position.items() if k != "identifier"} if position else None
    return json.dumps({
        "symbol": ctx["symbol"], "position": visible, "atr_m5": ctx.get("atr_m5"),
        "spread_pips": ctx.get("spread_pips"), "reference_price": ctx["reference_price"], "quote": {"bid": ctx["bid"], "ask": ctx["ask"]},
        "m5_closed_utc": ctx["m5_closed_utc"], "candles": ctx["candles"],
        "h1_indicators": ctx["h1_indicators"], "digits": ctx["digits"],
    }, separators=(",", ":"))


def call_provider(provider, model, key, data):
    if provider == "gemini":
        config = {"responseMimeType": "application/json", "temperature": 0, "maxOutputTokens": OUTPUT_TOKENS}
        if model.startswith("gemini-2.5-flash"):
            config["thinkingConfig"] = {"thinkingBudget": 0}
        response = request_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": key},
            {"contents": [{"parts": [{"text": SYSTEM + "\n" + data}]}], "generationConfig": config},
        )
        usage = response.get("usageMetadata", {})
        used_input = usage.get("promptTokenCount")
        used_output = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        candidate = next(iter(response.get("candidates", [])), {})
        raw = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []) if not p.get("thought"))
    else:
        response = request_json(
            "https://api.openai.com/v1/chat/completions", {"Authorization": "Bearer " + key},
            {"model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": data}],
             "response_format": {"type": "json_object"}, "max_completion_tokens": OUTPUT_TOKENS},
        )
        usage = response.get("usage", {})
        used_input = usage.get("prompt_tokens")
        used_output = usage.get("completion_tokens")
        choice = next(iter(response.get("choices", [])), {})
        raw = choice.get("message", {}).get("content") or ""
    return raw, (used_input, used_output)


def decision_risk(action, sl, tp, ctx):
    if action == "WAIT":
        return 0, "WAIT"
    position = ctx.get("position")
    if action in ("HOLD", "MODIFY", "CLOSE"):
        if position is None:
            return 0, "La acción requiere una posición propia vigente"
        if action != "MODIFY":
            return 1, "Acción sobre posición propia"
        action = position["side"]
    elif position:
        return 0, "Ya existe una posición propia en el símbolo"
    min_distance = ctx["trade_stops_level"] * ctx["point"]
    bid, ask = ctx["bid"], ctx["ask"]
    if action == "BUY":
        valid = sl < bid and tp > ask and min(bid - sl, tp - bid) >= min_distance
    else:
        valid = tp < bid and sl > ask and min(sl - ask, ask - tp) >= min_distance
    return int(valid), "Niveles coherentes con la cotización" if valid else "SL/TP incompatibles con el bid/ask o distancia mínima"


def register_provider(db, cycle_id, ctx, provider, model, max_call_usd, executor=None):
    if provider == "openai" and os.getenv("OPENAI_ENABLED") != "1":
        return "openai: desactivado en configuración"
    key = os.getenv(provider.upper() + "_API_KEY", "").strip()
    if not key:
        return f"{provider}: clave sin configurar"
    prices = provider_price(provider, model)
    payload = api_payload(ctx)
    # UTF-8 bytes plus envelope allowance provide a conservative local reservation for text.
    estimated = (((len((SYSTEM + payload).encode()) + 512) * prices[0] + OUTPUT_TOKENS * prices[1]) / 1e6
                 if prices else max_call_usd)
    if estimated > max_call_usd:
        return f"{provider}: reserva calculada excede la cota por llamada"
    now = utc_now()
    if not in_session(now) or session_end(now) - now <= timedelta(seconds=REQUEST_TIMEOUT):
        return f"{provider}: cierre de sesión próximo"
    if int(now.timestamp()) // 300 * 300 != int(datetime.fromisoformat(ctx["m5_closed_utc"]).timestamp()):
        return f"{provider}: la vela ya no es la última"
    claimed = claim(db, cycle_id, provider, now, estimated)
    if claimed != "reserved":
        return f"{provider}: {claimed}"
    cost = None
    try:
        started = time.monotonic()
        raw, tokens = call_provider(provider, model, key, payload)
        latency_ms = round((time.monotonic() - started) * 1000)
        received = utc_now().isoformat()
        if prices and all(type(n) is int and n >= 0 for n in tokens):
            cost = sum(n * rate for n, rate in zip(tokens, prices)) / 1e6
        action, reason, sl, tp = parse_decision(raw, strict=True)
        valid, note = decision_risk(action, sl, tp, ctx)
        with db:
            db.execute("""
                INSERT INTO prospective_decisions
                (cycle_id,provider,model,received_utc,action,reason,sl,tp,raw_json,valid,risk_note,cost_usd_est)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (cycle_id, provider, model, received, action, reason, sl, tp,
                  json.dumps({"decision": json.loads(raw) if isinstance(raw, str) else raw, "tokens": tokens,
                              "latency_ms": latency_ms, "prompt_version": PROMPT_VERSION,
                              "symbol": ctx["symbol"], "reference_price": ctx["reference_price"],
                              "m5_closed_utc": ctx["m5_closed_utc"]}, ensure_ascii=False), valid, note, cost or 0))
            db.execute("""UPDATE prospective_attempts SET status='saved',cost_usd_est=?
                          WHERE cycle_id=? AND provider=?""", (cost, cycle_id, provider))
    except Exception as exc:
        with db:
            db.execute("""UPDATE prospective_attempts SET status='error',cost_usd_est=?
                          WHERE cycle_id=? AND provider=?""", (cost, cycle_id, provider))
            db.execute("""
                INSERT INTO prospective_errors (cycle_id,provider,occurred_utc,error) VALUES (?,?,?,?)
            """, (cycle_id, provider, utc_now().isoformat(), str(exc)[:400]))
        return f"{provider}: error ({str(exc)[:150]})"
    same_candle = int(datetime.fromisoformat(received).timestamp()) // 300 * 300 == int(
        datetime.fromisoformat(ctx["m5_closed_utc"]).timestamp()
    )
    if executor and executor.provider == provider and valid and same_candle:
        if action in ("BUY", "SELL"):
            executor.enter(db, cycle_id, ctx["symbol"], action, sl, tp, received)
        elif action in ("MODIFY", "CLOSE"):
            executor.manage(db, cycle_id, ctx["symbol"], ctx["position"]["identifier"], action, sl, tp, received)
    return f"{provider}: {action} guardado"


def run_cycle(db, symbol, providers, models, max_call_usd, executor=None):
    now = utc_now()
    if not in_session(now):
        return [f"{symbol}: fuera de 02:00–10:00 en Nicaragua"]
    ctx = collect(symbol)
    closed = datetime.fromisoformat(ctx["m5_closed_utc"])
    if not in_session(closed) or not 0 <= (utc_now() - closed).total_seconds() < 300:
        return [f"{symbol}: vela fuera de sesión u obsoleta"]
    from app.prospective_outcomes import simulation_settings

    ctx["simulation"] = simulation_settings(symbol)
    canonical = json.dumps(ctx, sort_keys=True, separators=(",", ":"), allow_nan=False)
    sha = hashlib.sha256(canonical.encode()).hexdigest()
    cycle_id = hashlib.sha256((symbol + "|" + ctx["m5_closed_utc"]).encode()).hexdigest()[:24]
    with db:
        db.execute("""
            INSERT OR IGNORE INTO prospective_cycles
            (cycle_id,created_utc,symbol,m5_closed_utc,context_sha256,context_json,spread_pips,session_allowed)
            VALUES (?,?,?,?,?,?,?,?)
        """, (cycle_id, now.isoformat(), symbol, ctx["m5_closed_utc"], sha, canonical, ctx["spread_pips"], 1))
    # Every provider receives the same market snapshot, also after a restart mid-candle.
    stored = db.execute("SELECT context_json FROM prospective_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
    ctx = json.loads(stored["context_json"])
    return [f"{symbol} · {register_provider(db, cycle_id, ctx, provider, models[provider], max_call_usd, executor)}"
            for provider in dict.fromkeys(providers)]


def run_diagnostic(db, args):
    """Single read-only API diagnostic; never creates trade-eligible cycles."""
    if not args.allow_api_cost:
        raise ValueError("Diagnóstico requiere --allow-api-cost (consulta de API facturable)")
    if args.demo or args.loop:
        raise ValueError("Diagnóstico incompatible con --demo y --loop")
    models = {"gemini": args.gemini_model, "openai": args.openai_model}
    for symbol in dict.fromkeys(args.symbols):
        ctx = collect(symbol, diagnostic=True)  # Historical data permitted ONLY for diagnostics.
        print(f"{symbol}: DIAGNOSTIC_ONLY · vela M5 cerrada {ctx['m5_closed_utc']} · "
              f"antigüedad {ctx['snapshot_age_seconds']} s · SIN ÓRDENES")
        payload = json.dumps({"mode": "DIAGNOSTIC_ONLY", "historical": True,
                              "no_trading": True, "snapshot_age_seconds": ctx["snapshot_age_seconds"],
                              "symbol": ctx["symbol"], "m5_closed_utc": ctx["m5_closed_utc"],
                              "reference_price": ctx["reference_price"], "candles": ctx["candles"],
                              "h1_indicators": ctx["h1_indicators"], "digits": ctx["digits"]},
                             separators=(",", ":"))
        for provider in dict.fromkeys(args.providers):
            if provider == "openai" and os.getenv("OPENAI_ENABLED") != "1":
                print("OpenAI desactivado en configuración")
                continue
            model = models[provider]
            # Uniqueness includes provider AND model: switching models should not
            # silently skip the API test for an already-observed M5 candle.
            diagnostic_id = hashlib.sha256(
                f"diagnostic|{symbol}|{ctx['m5_closed_utc']}|{provider}|{model}".encode()
            ).hexdigest()[:24]
            key = os.getenv(provider.upper() + "_API_KEY", "").strip()
            if not key:
                print(f"{symbol} · {provider}: clave API sin configurar")
                continue
            prices = provider_price(provider, model)
            reserve = (((len((SYSTEM + payload).encode()) + 512) * prices[0] + OUTPUT_TOKENS * prices[1]) / 1e6
                       if prices else args.max_call_usd)
            if reserve > args.max_call_usd:
                print(f"{symbol} · {provider}: reserva excede --max-call-usd")
                continue
            now = utc_now()
            from app.prospective_store import write_lock
            with write_lock(db):
                exists = db.execute("""SELECT status,error FROM diagnostic_calls
                    WHERE diagnostic_id=? AND provider=?""", (diagnostic_id, provider)).fetchone()
                # A rejected HTTP 400 request can be retried after fixing its parameters.
                # Preserve the failed row as an archived attempt, without retaining its
                # pre-request budget reservation. Never release uncertain network failures.
                if exists and exists["status"] == "error" and str(exists["error"] or "").startswith("HTTP 400"):
                    old_id = diagnostic_id
                    attempt = 1
                    while True:
                        archive_id = hashlib.sha256(f"{old_id}|{provider}|failed|{attempt}".encode()).hexdigest()[:24]
                        conflict = db.execute("SELECT 1 FROM diagnostic_calls WHERE diagnostic_id=? AND provider=?",
                                              (archive_id, provider)).fetchone()
                        if not conflict:
                            break
                        attempt += 1
                    db.execute("""UPDATE diagnostic_calls SET diagnostic_id=?,reserved_usd=0
                        WHERE diagnostic_id=? AND provider=?""", (archive_id, old_id, provider))
                    exists = None
                current = budget(db)[provider]
                if exists:
                    reason = "ya diagnosticado para esta vela"
                elif reserve > current["remaining"] + 1e-10:
                    reason = "presupuesto acumulado insuficiente"
                else:
                    reason = None
                    db.execute("""INSERT INTO diagnostic_calls
                        (diagnostic_id,provider,symbol,model,started_utc,reserved_usd,status)
                        VALUES (?,?,?,?,?,?,'reserved')""",
                        (diagnostic_id, provider, symbol, model, now.isoformat(), reserve))
            if reason:
                print(f"{symbol} · {provider}: {reason}")
                continue
            cost = None
            try:
                raw, tokens = call_provider(provider, model, key, payload)
                if prices and all(type(n) is int and n >= 0 for n in tokens):
                    cost = sum(n * rate for n, rate in zip(tokens, prices)) / 1e6
                action, explanation, sl, tp = parse_decision(raw, diagnostic=True)
                # A diagnostic action is recorded ONLY in diagnostic_calls, never prospective_decisions.
                with db:
                    db.execute("""UPDATE diagnostic_calls SET received_utc=?,cost_usd_est=?,
                        status='DIAGNOSTIC_ONLY',action=?,reason=?
                        WHERE diagnostic_id=? AND provider=?""",
                        (utc_now().isoformat(), cost, action, explanation, diagnostic_id, provider))
                print(f"{symbol} · {provider}: DIAGNOSTIC_ONLY · {action} · costo estimado: {cost if cost is not None else 'desconocido'} USD · SIN ÓRDENES")
            except Exception as exc:
                # Explicit HTTP 400 validation rejections do not create model output;
                # release the reservation. Keep it for timeouts/ambiguous failures.
                rejected = isinstance(exc, RuntimeError) and str(exc).startswith("HTTP 400")
                with db:
                    db.execute("""UPDATE diagnostic_calls SET received_utc=?,cost_usd_est=?,
                        reserved_usd=CASE WHEN ? THEN 0 ELSE reserved_usd END,
                        status='error',error=? WHERE diagnostic_id=? AND provider=?""",
                        (utc_now().isoformat(), cost, int(rejected), str(exc)[:400], diagnostic_id, provider))
                print(f"{symbol} · {provider}: error diagnóstico ({str(exc)[:400]})")


def run(args, db, executor):
    from app.prospective_outcomes import finish_sessions

    models = {"gemini": args.gemini_model, "openai": args.openai_model}
    next_report = 0
    next_calendar_sync = 0
    maintenance_ok = True
    while True:
        now = utc_now()
        if not args.report_only:
            update_runtime(db, "demo" if executor else "dry-run", args.execute_provider if executor else args.providers[0])
        # Refresh public news in observation mode too; failures never authorize orders.
        if args.loop and os.getenv("FINNHUB_API_KEY") and time.monotonic() >= next_calendar_sync:
            next_calendar_sync = time.monotonic() + 30 * 60
            try:
                from app.news_calendar_sync import sync
                target = db_path().parent / "news_calendar_candidate.json"
                sync(os.environ["FINNHUB_API_KEY"], target)
            except Exception as exc:
                print(f"Calendario: actualización fallida ({exc}); entradas sujetas a bloqueo", file=sys.stderr)
        has_open = bool(executor)
        maintenance_ok = True
        if executor:
            try:
                has_open = executor.maintain(db)
            except Exception as exc:
                maintenance_ok = False
                print(f"MT5 demo: {exc}; nuevas entradas bloqueadas", file=sys.stderr)
        if time.monotonic() >= next_report:
            next_report = time.monotonic() + 60
            try:
                finish_sessions(db)
            except Exception as exc:
                print(f"Reportes: {exc}", file=sys.stderr)
        if args.report_only:
            break
        until_reached = args.until and now.astimezone(LOCAL).date() >= args.until
        if until_reached and not has_open:
            break
        # Demo remains alive to manage previously opened positions through any disconnect.
        if not until_reached and (not executor or maintenance_ok):
            for symbol in args.symbols:
                try:
                    for line in run_cycle(db, symbol, args.providers, models, args.max_call_usd, executor):
                        if not args.loop or not any(s in line for s in ("ya procesado", "fuera de", "presupuesto acumulado insuficiente")):
                            print(line)
                except Exception as exc:
                    print(f"{symbol}: {exc}", file=sys.stderr)
        if not args.loop:
            break
        time.sleep(10)


def main():
    load_settings()
    parser = argparse.ArgumentParser(description="AI Trader Research Lab · prospectivo MT5 demo")
    parser.add_argument("--db", default=db_path())
    parser.add_argument("--symbols", nargs="+", default=live_symbols()[:1])
    parser.add_argument("--providers", nargs="+", choices=["gemini", "openai"], default=["gemini"])
    parser.add_argument("--gemini-model", default=os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite")
    parser.add_argument("--openai-model", default=os.getenv("OPENAI_MODEL") or "gpt-5.4-mini")
    parser.add_argument("--max-call-usd", type=float, default=0.05)
    parser.add_argument("--until", type=date.fromisoformat, help="Fecha exclusiva de entradas, hora de Nicaragua")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--report-only", action="store_true")
    modes.add_argument("--diagnostic", action="store_true", help="Una consulta por proveedor sin operar, incluso fuera de sesión")
    parser.add_argument("--allow-api-cost", action="store_true", help="Autorización explícita para llamadas de API facturables")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Habilita ejecución exclusivamente en la cuenta demo indicada")
    parser.add_argument("--execute-provider", choices=["gemini", "openai"], default="gemini")
    args = parser.parse_args()
    if not (args.status or args.report_only) and not args.allow_api_cost:
        parser.error("Las consultas requieren --allow-api-cost")
    if not (args.status or args.report_only) and "openai" in args.providers and os.getenv("OPENAI_ENABLED") != "1":
        parser.error("OpenAI desactivado. Solo habilitalo con crédito verificado y OPENAI_ENABLED=1")
    if not 0 < args.max_call_usd <= CAP_USD or not args.symbols or any(not valid_market_symbol(s) for s in args.symbols):
        parser.error("Verificá los símbolos y el límite por llamada")
    if args.demo and (not args.loop or args.execute_provider not in args.providers or args.status or args.report_only or args.diagnostic):
        parser.error("--demo requiere --loop y que --execute-provider esté en --providers")
    if not (args.status or args.report_only):
        for p, model in (("gemini", args.gemini_model), ("openai", args.openai_model)):
            if p in args.providers:
                if not model.strip() or not all(c.isalnum() or c in "-_." for c in model):
                    parser.error(f"Modelo de {p} inválido")
                try:
                    provider_price(p, model)
                except ValueError as exc:
                    parser.error(str(exc))
    with closing(connect(args.db)) as db:
        if args.status:
            day = utc_now().astimezone(LOCAL).date().isoformat()
            print(json.dumps({
                "fecha_nicaragua": day, "db": str(args.db), "presupuesto": budget(db), "actividad_api_hoy": budget(db, day),
                "ciclos": db.execute("SELECT COUNT(*) FROM prospective_cycles").fetchone()[0],
                "decisiones": db.execute("SELECT COUNT(*) FROM prospective_decisions").fetchone()[0],
                "evaluaciones": db.execute("SELECT COUNT(*) FROM prospective_outcomes").fetchone()[0],
                "diagnosticos": [dict(r) for r in db.execute("""SELECT provider,status,action,started_utc,cost_usd_est,error FROM diagnostic_calls ORDER BY started_utc DESC LIMIT 10""")],
            }, indent=2))
            return
        if args.diagnostic:
            try:
                run_diagnostic(db, args)
            except (ValueError, RuntimeError) as exc:
                parser.exit(1, f"Diagnóstico: {exc}\n")
            return
        executor = None
        guard = nullcontext()
        if args.demo:
            from app.demo_execution import DemoExecutor, runner_lock
            try:
                executor = DemoExecutor.from_env(args.execute_provider, args.symbols)
            except (ValueError, RuntimeError) as exc:
                parser.error(str(exc))
            guard = runner_lock(executor.login)
        try:
            with guard:
                run(args, db, executor)
        except KeyboardInterrupt:
            print("Proceso detenido")
        except sqlite3.OperationalError as exc:
            parser.exit(1, f"SQLite: {exc}\n")


if __name__ == "__main__":
    main()
