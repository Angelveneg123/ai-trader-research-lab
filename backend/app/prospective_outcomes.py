"""Evaluate decisions using later MT5 ticks and write daily session reports."""
import json
import math
import os
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, time, timedelta

from .market_symbols import settings_path
from .prospective_store import LOCAL, UTC, budget, session_end, utc_now, write_lock

MAX_TICK_GAP_MS = 120_000
MAX_ENTRY_DELAY_MS = 60_000
CLOCK_TOLERANCE_MS = 5_000


def simulation_settings(symbol):
    path = os.getenv("MT5_EXECUTION_CONFIG")
    if path:
        try:
            rule = json.loads(settings_path(path).read_text(encoding="utf-8-sig"))[symbol]
            commission = float(rule["commission_usd_per_lot_roundtrip"])
            slippage = float(rule["slippage_buffer_points_per_side"])
            if math.isfinite(commission) and commission >= 0 and math.isfinite(slippage) and slippage >= 0:
                return {"commission": commission, "slippage_points": slippage, "source": "configuración de ejecución"}
        except (OSError, KeyError, TypeError, ValueError):
            pass
    return {"commission": 0, "slippage_points": 1, "source": "escenario: comisión 0 USD, 1 punto de deslizamiento por lado"}


def fetch_ticks(symbol, start, end):
    from .mt5_connection import connection

    with connection() as (mt5, _, _):
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Símbolo no disponible: {symbol}")
        ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_INFO)
        if ticks is None:
            raise RuntimeError(f"Historial de ticks no disponible: {symbol}")
        records = []
        for tick in ticks:
            bid, ask = float(tick["bid"]), float(tick["ask"])
            if math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask:
                records.append((int(tick["time_msc"]), bid, ask))
        return sorted(records, key=lambda t: t[0])


def tick_time(milliseconds):
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat()


def evaluate(row, ctx, ticks, times, end):
    if row["action"] == "WAIT":
        return ("WAIT", None, None, None, None, None, None, "Sin entrada")
    if row["action"] in ("HOLD", "MODIFY", "CLOSE"):
        return ("MANAGEMENT", None, None, None, None, None, None, "Gestión registrada en el diario demo")
    if not row["valid"]:
        return ("INVALID", None, None, None, None, None, None, row["risk_note"])
    received = datetime.fromisoformat(row["received_utc"])
    received_ms = int(received.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    i = bisect_right(times, received_ms + CLOCK_TOLERANCE_MS)
    if i == len(ticks) or times[i] >= end_ms or times[i] - received_ms > MAX_ENTRY_DELAY_MS:
        return ("INDETERMINATE", None, None, None, None, None, None, "Sin cotización oportuna después de la decisión")
    side = 1 if row["action"] == "BUY" else -1
    sl, tp = row["sl"], row["tp"]
    assumptions = ctx.get("simulation") or simulation_settings(row["symbol"])
    adverse = assumptions["slippage_points"] * ctx["point"]
    entry_ms, bid, ask = ticks[i]
    entry = (ask if side == 1 else bid) + side * adverse
    if not (sl < bid <= entry < tp if side == 1 else tp < entry <= ask < sl):
        return ("NO_ENTRY", tick_time(entry_ms), None, None, None, None, None,
                "SL/TP incompatibles con la primera cotización disponible")
    entry_mid = (ask + bid) / 2
    previous = entry_ms
    for j in range(i + 1, len(ticks)):
        at, bid, ask = ticks[j]
        if at - previous > MAX_TICK_GAP_MS:
            break
        previous = at
        quote = bid if side == 1 else ask
        outcome = None
        if at >= end_ms:
            outcome = "SESSION_CLOSE"
        elif side * (quote - sl) <= 0:
            outcome = "SL"
        elif side * (quote - tp) >= 0:
            outcome = "TP"
        if outcome:
            exit_price = quote - side * adverse
            pip = ctx["pip_size"]
            exit_mid = (bid + ask) / 2
            gross = side * (exit_mid - entry_mid) / pip
            spread_slippage = gross - side * (exit_price - entry) / pip
            currency = ctx.get("quote_currency")
            base_symbol = row["symbol"].upper().startswith("USDJPY")
            pip_usd = ctx["contract_size"] * pip * (1 if currency == "USD" else 1 / exit_mid if currency == "JPY" and base_symbol else 0)
            commission = assumptions["commission"]
            if commission and pip_usd <= 0:
                return ("INDETERMINATE", tick_time(entry_ms), tick_time(at), entry, exit_price, None, None,
                        "Conversión a USD de la comisión no disponible")
            costs = spread_slippage + (commission / pip_usd if commission else 0)
            return (outcome, tick_time(entry_ms), tick_time(at), entry, exit_price, round(gross - costs, 5),
                    round(costs, 5), assumptions["source"])
    return ("INDETERMINATE", tick_time(entry_ms), None, entry, None, None, None,
            "Hueco de cotizaciones o cierre sin ticks")


def send_report(db, day, message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if os.getenv("TELEGRAM_ENABLED") != "1" or not token or not chat:
        return
    with write_lock(db):
        claimed = db.execute("""
            UPDATE prospective_reports SET telegram_status='sending'
            WHERE local_day=? AND telegram_status='pending'
        """, (day,)).rowcount
    if not claimed:
        return
    from prospectivo_v22 import request_json

    try:
        reply = request_json(f"https://api.telegram.org/bot{token}/sendMessage", {},
                             {"chat_id": chat, "text": message[:4000]}, timeout=10)
        status = "sent" if reply.get("ok") else "rejected"
    except Exception as exc:
        if str(exc).startswith(("HTTP 400", "HTTP 401", "HTTP 403", "HTTP 404", "HTTP 429")):
            status = "rejected"
        else:
            status = "unconfirmed"
    with db:
        db.execute("UPDATE prospective_reports SET telegram_status=? WHERE local_day=?", (status, day))


def make_report(db, day):
    opening = datetime.combine(day, time(2), LOCAL).astimezone(UTC).isoformat()
    end = datetime.combine(day, time(10), LOCAL).astimezone(UTC).isoformat()
    local_day = day.isoformat()
    lines = [f"AI Trader Research Lab · {local_day} (Nicaragua)"]
    for provider, b in budget(db, local_day).items():
        rows = db.execute("""
            SELECT c.symbol, COUNT(*) AS total, SUM(d.action='WAIT') AS wait,
                   COUNT(o.net_pips) AS evaluable, SUM(COALESCE(o.net_pips>0,0)) AS positive,
                   SUM(o.outcome IS NULL) AS pending, SUM(COALESCE(o.outcome IN ('INDETERMINATE','INVALID','NO_ENTRY'),0)) AS discarded,
                   SUM(o.net_pips) AS net_pips
            FROM prospective_decisions d JOIN prospective_cycles c ON c.cycle_id=d.cycle_id
            LEFT JOIN prospective_outcomes o ON o.cycle_id=d.cycle_id AND o.provider=d.provider
            WHERE d.provider=? AND c.m5_closed_utc>=? AND c.m5_closed_utc<? GROUP BY c.symbol ORDER BY c.symbol
        """, (provider, opening, end)).fetchall()
        for row in rows:
            total = f"{row['net_pips']:+.2f} pips netos simulados" if row["evaluable"] else "sin resultados netos"
            lines.append(f"{provider} {row['symbol']}: {row['total']} decisiones, {row['wait']} WAIT, "
                         f"{row['evaluable']} evaluables ({row['positive']} positivas), "
                         f"{row['pending']} pendientes, {row['discarded']} descartadas. {total}.")
        total = budget(db)[provider]
        lines.append(f"API {provider}: {b['attempts']} intentos hoy · USD {b['spent']:.4f} estimados "
                     f"+ {b['reserved']:.4f} por conciliar · USD {total['remaining']:.4f} disponibles para la prueba.")
    demo = db.execute("""
        SELECT realized_usd,floating_usd,positions,loss_blocked FROM prospective_demo_status WHERE local_day=?
    """, (local_day,)).fetchone()
    if demo:
        lines.append(f"MT5 demo: USD {demo['realized_usd']:+.2f} realizado, {demo['floating_usd']:+.2f} flotante, "
                     f"{demo['positions']} posiciones, bloqueo diario {'activo' if demo['loss_blocked'] else 'inactivo'}.")
    else:
        actual = db.execute("SELECT COUNT(*), SUM(net_usd) FROM prospective_demo_deals WHERE local_day=?", (local_day,)).fetchone()
        if actual[0]:
            lines.append(f"Historial MT5 demo: {actual[0]} ejecuciones registradas, USD {actual[1]:+.2f} realizado.")
    return "\n".join(lines)


def finish_sessions(db):
    now = utc_now()
    past = db.execute("""
        SELECT d.*,c.symbol,c.context_json,c.m5_closed_utc FROM prospective_decisions d
        JOIN prospective_cycles c ON c.cycle_id=d.cycle_id
        LEFT JOIN prospective_outcomes o ON o.cycle_id=d.cycle_id AND o.provider=d.provider
        WHERE o.cycle_id IS NULL ORDER BY d.received_utc
    """).fetchall()
    groups = defaultdict(list)
    days = set()
    today = now.astimezone(LOCAL).date()
    if today.weekday() < 5 and now >= session_end(now) + timedelta(minutes=2):
        days.add(today)
    for row in past:
        close = datetime.fromisoformat(row["m5_closed_utc"])
        if now >= session_end(close) + timedelta(minutes=2):
            day = close.astimezone(LOCAL).date()
            groups[(day, row["symbol"])].append(row)
            days.add(day)
    for (day, symbol), rows in groups.items():
        end = datetime.combine(day, time(10), LOCAL).astimezone(UTC)
        needs_ticks = [r for r in rows if r["valid"] and r["action"] in ("BUY", "SELL")]
        ticks = []
        if needs_ticks:
            start = min(datetime.fromisoformat(r["received_utc"]) for r in needs_ticks)
            if start < end:
                try:
                    ticks = fetch_ticks(symbol, start, end + timedelta(minutes=2))
                except RuntimeError as exc:
                    print(str(exc))
        times = [t[0] for t in ticks]
        with db:
            for row in rows:
                if row in needs_ticks and not ticks and now < end + timedelta(days=1):
                    continue
                data = evaluate(row, json.loads(row["context_json"]), ticks, times, end)
                db.execute("""
                    INSERT OR IGNORE INTO prospective_outcomes
                    (cycle_id,provider,outcome,evaluated_utc,entry_utc,exit_utc,entry_price,exit_price,
                     net_pips,cost_pips,detail) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (row["cycle_id"], row["provider"], data[0], now.isoformat(), *data[1:]))
    pending = db.execute("SELECT local_day FROM prospective_reports WHERE telegram_status='pending'").fetchall()
    days.update(datetime.fromisoformat(row[0]).date() for row in pending)
    for day in sorted(days):
        report = make_report(db, day)
        with db:
            db.execute("""
                INSERT INTO prospective_reports (local_day,created_utc,body,telegram_status)
                VALUES (?,?,?,'pending') ON CONFLICT(local_day) DO UPDATE SET body=excluded.body
            """, (day.isoformat(), now.isoformat(), report))
        still_waiting = any(group_day == day for group_day, _ in groups) and db.execute("""
            SELECT 1 FROM prospective_decisions d
            JOIN prospective_cycles c ON c.cycle_id=d.cycle_id
            LEFT JOIN prospective_outcomes o ON o.cycle_id=d.cycle_id AND o.provider=d.provider
            WHERE o.cycle_id IS NULL AND substr(c.m5_closed_utc,1,10)=? LIMIT 1
        """, (day.isoformat(),)).fetchone()
        latest_send = datetime.combine(day, time(10, 15), LOCAL).astimezone(UTC)
        if not still_waiting or now >= latest_send:
            send_report(db, day.isoformat(), report)



def news_snapshot():
    from .demo_execution import calendar_status, utc_date

    path = os.getenv("MT5_NEWS_CALENDAR")
    now = utc_now()
    if path:
        try:
            file = settings_path(path)
            calendar = json.loads(file.read_text(encoding="utf-8-sig"))
            upcoming = []
            for row in calendar["events"]:
                at = utc_date(row["at_utc"])
                if now - timedelta(minutes=20) <= at <= now + timedelta(days=7) and row["impact"] == "high":
                    upcoming.append({"at_utc": at.isoformat(), "currency": row["currency"], "title": row["title"]})
            issues = {name: calendar_status(file, currencies, now) for name, currencies in (
                ("EURUSDmicro", {"EUR", "USD"}), ("USDJPYmicro", {"USD", "JPY"}), ("XAUUSDmicro", {"USD"}))}
            return {"covered": any(issue is None or issue.startswith("Noticias de alto impacto")
                                   for issue in issues.values()), "source": calendar.get("source"),
                    "retrieved_utc": calendar.get("retrieved_utc"), "status_by_symbol": issues,
                    "events": sorted(upcoming, key=lambda r: r["at_utc"])[:25]}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return {"covered": False, "events": [], "source": None, "retrieved_utc": None, "status_by_symbol": {}}
