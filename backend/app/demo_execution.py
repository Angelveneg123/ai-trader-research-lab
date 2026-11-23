"""MT5 execution for an explicitly selected USD demo account."""
import json
import math
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from .mt5_connection import backend_module, connection as mt5_connection, ensure_demo
from .market_symbols import settings_path
from .prospective_store import LOCAL, UTC, entries_blocked, in_session, session_end, utc_now, write_lock

MAGIC = 220026
RISK_USD = 0.25
DAILY_LIMIT_USD = 1.0
NEWS_WINDOW = timedelta(minutes=20)


@contextmanager
def runner_lock(login):
    db = sqlite3.connect(Path(tempfile.gettempdir()) / f"ai_trader_demo_{login}.sqlite3", timeout=0.1)
    try:
        db.execute("BEGIN EXCLUSIVE")
        yield
    finally:
        db.close()


def event(db, login, symbol, kind, detail):
    with db:
        db.execute("""
            INSERT INTO prospective_demo_events (recorded_utc,account,symbol,kind,detail)
            VALUES (?,?,?,?,?)
        """, (utc_now().isoformat(), login, symbol, kind, detail))


def utc_date(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Se requieren fechas con zona UTC")
    return parsed.astimezone(UTC)


def calendar_status(path, currencies, now):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        start, end = (utc_date(data[k]) for k in ("coverage_start_utc", "coverage_end_utc"))
        if data.get("coverage_verified") is not True or not str(data.get("source") or "").strip():
            return "Calendario sin cobertura verificada"
        noted = data.get("currencies")
        if not isinstance(noted, list) or not all(isinstance(symbol, str) for symbol in noted):
            return "Calendario sin divisas declaradas"
        relevant = {currency for currency in currencies if currency not in {"XAU", "XAG"}}
        if not relevant <= set(noted):
            return "Calendario sin cobertura para todas las divisas del símbolo"
        if start > now - NEWS_WINDOW or end < now + NEWS_WINDOW:
            return "Calendario económico sin cobertura vigente"
        # Coverage is not sufficient: a stale download must never authorize orders.
        retrieved = utc_date(data["retrieved_utc"])
        if retrieved > now + timedelta(minutes=2) or now - retrieved > timedelta(minutes=60):
            return "Calendario económico desactualizado"
        if not isinstance(data["events"], list):
            raise ValueError("Lista de noticias inválida")
        blocked = []
        for news in data["events"]:
            at = utc_date(news["at_utc"])
            if not start <= at <= end or news["impact"] not in ("high", "medium", "low"):
                raise ValueError("Evento inválido")
            currency, title = news["currency"], news["title"]
            if not isinstance(currency, str) or not currency.isalpha() or len(currency) != 3 or not isinstance(title, str):
                raise ValueError("Divisa o título inválido")
            if news["impact"] == "high" and currency.upper() in currencies and abs(at - now) <= NEWS_WINDOW:
                blocked.append(title[:100])
        return f"Noticias de alto impacto: {', '.join(blocked)}" if blocked else None
    except (OSError, ValueError, KeyError, TypeError):
        return "Calendario económico ausente o inválido"


def bounded_number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        raise ValueError("Costo, desviación o spread de ejecución inválido")
    return value


def protected_loss(mt5, trade_type, symbol, volume, entry, stop, point, slippage_points, commission_per_lot):
    """Conservative two-sided adverse execution buffer, never a price guarantee."""
    if not all(math.isfinite(float(x)) for x in (volume, entry, stop, point, slippage_points, commission_per_lot)):
        raise RuntimeError("Parámetros de riesgo no finitos")
    if volume <= 0 or point <= 0 or slippage_points < 0 or commission_per_lot < 0:
        raise RuntimeError("Parámetros de riesgo inválidos")
    buy = trade_type == mt5.ORDER_TYPE_BUY
    if not buy and trade_type != mt5.ORDER_TYPE_SELL:
        raise RuntimeError("Dirección de operación inválida")
    buffer = slippage_points * point
    worst_entry = entry + buffer if buy else entry - buffer
    worst_exit = stop - buffer if buy else stop + buffer
    if (buy and worst_exit >= worst_entry) or (not buy and worst_exit <= worst_entry):
        raise RuntimeError("Stop no representa una pérdida")
    profit = mt5.order_calc_profit(trade_type, symbol, volume, worst_entry, worst_exit)
    if profit is None or not math.isfinite(profit) or profit >= 0:
        raise RuntimeError("MT5 no pudo calcular pérdida protegida")
    return -profit + commission_per_lot * volume


def deal_value(deal):
    return sum(float(getattr(deal, key, 0)) for key in ("profit", "commission", "swap", "fee"))


def floor_volume(info, desired):
    step = Decimal(str(info.volume_step))
    minimum = Decimal(str(info.volume_min))
    cap = min(Decimal(str(info.volume_max)), Decimal(str(desired)))
    if step <= 0 or minimum <= 0 or cap < minimum:
        return 0
    steps = ((cap - minimum) / step).to_integral_value(rounding=ROUND_FLOOR)
    return float(minimum + steps * step)


def tick_for(mt5, symbol, now, max_age=15):
    tick = mt5.symbol_info_tick(symbol)
    if (not tick or not all(math.isfinite(p) for p in (tick.bid, tick.ask))
            or not 0 < tick.bid <= tick.ask or not -5 <= now.timestamp() - tick.time <= max_age):
        raise RuntimeError(f"Sin cotización vigente para {symbol}")
    return tick


class DemoExecutor:
    def __init__(self, login, provider, settings, calendar, mt5):
        self.login = login
        self.provider = provider
        self.settings = settings
        self.calendar = calendar
        self.mt5 = mt5

    @classmethod
    def from_env(cls, provider, symbols):
        mt5 = backend_module()

        try:
            login = int(os.environ["MT5_DEMO_LOGIN"])
            if login <= 0:
                raise ValueError
            path = settings_path(os.environ["MT5_EXECUTION_CONFIG"])
            calendar = settings_path(os.environ["MT5_NEWS_CALENDAR"])
            config = json.loads(path.read_text(encoding="utf-8-sig"))
            for symbol in symbols:
                rule = config[symbol]
                bounded_number(rule["commission_usd_per_lot_roundtrip"], 0, 100000)
                if rule.get("commission_verified") is not True or not str(rule.get("commission_source") or "").strip():
                    raise ValueError("Falta fuente de la comisión verificada")
                bounded_number(rule["max_spread_points"], 1e-8, 100000)
                bounded_number(rule["slippage_buffer_points_per_side"], 1, 10000)
                if type(rule["slippage_buffer_points_per_side"]) is not int:
                    raise ValueError
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError("Configurá MT5_DEMO_LOGIN, MT5_EXECUTION_CONFIG y MT5_NEWS_CALENDAR según la guía") from exc
        return cls(login, provider, config, calendar, mt5)

    @contextmanager
    def connection(self, trading=False):
        with mt5_connection(self.mt5, login=self.login, trading=trading) as (_, account, _):
            yield account

    def positions(self):
        rows = self.mt5.positions_get()
        if rows is None:
            raise RuntimeError("MT5 no devolvió posiciones")
        return rows

    def status(self, db, account, positions, now):
        local_day = now.astimezone(LOCAL).date().isoformat()
        start = datetime.combine(now.astimezone(LOCAL).date(), time.min, LOCAL).astimezone(UTC)
        oldest = db.execute("""SELECT MIN(updated_utc) FROM prospective_demo_entries
            WHERE account=? AND status IN ('sending','unconfirmed')""", (self.login,)).fetchone()[0]
        history_start = min(start, datetime.fromisoformat(oldest)) if oldest else start
        deals = self.mt5.history_deals_get(history_start, now)
        if deals is None:
            raise RuntimeError("MT5 no devolvió el historial de ejecuciones")
        own = [p for p in positions if p.magic == MAGIC]
        ids = {p.identifier for p in own}
        ids.update(r[0] for r in db.execute(
            "SELECT position_id FROM prospective_demo_positions WHERE account=?", (self.login,)))
        ids.update(d.position_id for d in deals if d.magic == MAGIC and d.position_id)
        for d in deals:
            if d.magic == MAGIC and d.position_id and d.entry == self.mt5.DEAL_ENTRY_IN:
                with db:
                    db.execute("""
                        UPDATE prospective_demo_entries SET status='filled',position_id=?,updated_utc=?,detail=?
                        WHERE account=? AND order_comment=? AND status IN ('sending','unconfirmed')
                    """, (d.position_id, now.isoformat(), f"Reconciliada con deal {d.ticket}", self.login, d.comment))
        ours = [d for d in deals if d.magic == MAGIC or d.position_id in ids]
        realized = sum(deal_value(d) for d in ours if datetime.fromtimestamp(d.time, UTC) >= start)
        floating = sum(deal_value(p) for p in own)
        if not all(math.isfinite(v) for v in (realized, floating, account.balance)):
            raise RuntimeError("MT5 devolvió valores monetarios inválidos")
        with db:
            db.executemany("""
                INSERT OR IGNORE INTO prospective_demo_deals
                (account,ticket,position_id,local_day,happened_utc,symbol,entry,reason,volume,price,net_usd)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, [(self.login, d.ticket, d.position_id, datetime.fromtimestamp(d.time, UTC).astimezone(LOCAL).date().isoformat(),
                   datetime.fromtimestamp(d.time, UTC).isoformat(), d.symbol, d.entry, d.reason,
                   d.volume, d.price, deal_value(d)) for d in ours])
            if realized + floating <= -DAILY_LIMIT_USD:
                db.execute("INSERT OR IGNORE INTO prospective_demo_days VALUES (?,?,1)", (self.login, local_day))
            blocked = db.execute("SELECT loss_blocked FROM prospective_demo_days WHERE account=? AND local_day=?",
                                 (self.login, local_day)).fetchone()
            db.execute("""
                INSERT OR REPLACE INTO prospective_demo_status
                (id,updated_utc,balance_usd,local_day,realized_usd,floating_usd,positions,loss_blocked)
                VALUES (1,?,?,?,?,?,?,?)
            """, (now.isoformat(), account.balance, local_day, realized, floating, len(own), int(bool(blocked))))
        pnl = realized + floating
        previous = db.execute("SELECT peak_pnl_usd FROM demo_metrics WHERE id=1 AND local_day=?", (local_day,)).fetchone()
        peak = max(0, pnl, previous[0] if previous else 0)
        open_rows = [{"symbol": p.symbol, "volume": p.volume, "price_open": p.price_open,
                      "sl": p.sl, "tp": p.tp, "floating_usd": deal_value(p),
                      "side": "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL"} for p in own]
        with db:
            db.execute("INSERT OR REPLACE INTO demo_metrics VALUES (1,?,?,?,?,?)",
                       (account.equity, peak - pnl, peak, local_day, json.dumps(open_rows)))
        return realized, bool(blocked)

    def select_filling(self, request, info):
        mt5 = self.mt5
        fillings = []
        if info.filling_mode & 1:
            fillings.append(mt5.ORDER_FILLING_FOK)
        if info.filling_mode & 2:
            fillings.append(mt5.ORDER_FILLING_IOC)
        if info.trade_exemode in (mt5.SYMBOL_TRADE_EXECUTION_INSTANT, mt5.SYMBOL_TRADE_EXECUTION_REQUEST):
            fillings.extend((mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC))
        for filling in dict.fromkeys(fillings):
            candidate = {**request, "type_filling": filling}
            if info.trade_exemode == mt5.SYMBOL_TRADE_EXECUTION_MARKET:
                candidate.pop("price", None)
            checked = mt5.order_check(candidate)
            if checked is not None and checked.retcode == 0:
                return candidate
        raise RuntimeError("MT5 order_check rechazó la solicitud FOK/IOC")

    def close_position(self, db, position):
        mt5 = self.mt5
        try:
            with self.connection(trading=True):
                current = mt5.positions_get(ticket=position.ticket)
                if current is None:
                    raise RuntimeError("MT5 no pudo verificar el ticket")
                if not current:
                    return True
                p = current[0]
                if p.magic != MAGIC:
                    raise RuntimeError("El ticket no pertenece al laboratorio")
                info = mt5.symbol_info(p.symbol)
                if not info:
                    raise RuntimeError("Especificaciones MT5 no disponibles")
                tick = tick_for(mt5, p.symbol, utc_now(), max_age=60)
                buy_position = p.type == mt5.POSITION_TYPE_BUY
                request = self.select_filling({
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "position": p.ticket,
                    "volume": p.volume, "magic": MAGIC, "comment": "AITrader close",
                    "type": mt5.ORDER_TYPE_SELL if buy_position else mt5.ORDER_TYPE_BUY,
                    "price": tick.bid if buy_position else tick.ask,
                    "deviation": self.settings.get(p.symbol, {}).get("slippage_buffer_points_per_side", 10),
                    "type_time": mt5.ORDER_TIME_GTC,
                }, info)
                active = mt5.account_info()
                ensure_demo(mt5, active, self.login)
                result = mt5.order_send(request)
                if result is None or result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                    raise RuntimeError(f"Cierre no confirmado: {getattr(result, 'retcode', 'sin respuesta')}")
                kind = "CLOSE" if result.retcode == mt5.TRADE_RETCODE_DONE else "CLOSE_PARTIAL"
                event(db, self.login, p.symbol, kind, f"Precio {result.price}")
                remaining = mt5.positions_get(ticket=p.ticket)
                return remaining is not None and not remaining
        except (RuntimeError, OSError) as exc:
            event(db, self.login, position.symbol, "CLOSE_PENDING", str(exc))
            return False

    def maintain(self, db):
        now = utc_now()
        overdue = []
        with self.connection():
            positions = self.positions()
            owned = {position.identifier: position for position in positions if position.magic == MAGIC}
            for row in db.execute("""SELECT cycle_id,position_id,action,detail FROM demo_management WHERE account=?
                                     AND status IN ('sending','unconfirmed')""", (self.login,)).fetchall():
                position = owned.get(row["position_id"])
                verified = position is None
                if position is not None and row["action"] == "MODIFY":
                    try:
                        target = json.loads(row["detail"])
                        verified = (abs(position.sl - target["sl"]) < target["step"] / 2
                                    and abs(position.tp - target["tp"]) < target["step"] / 2)
                    except (KeyError, TypeError, ValueError):
                        verified = False
                if verified:
                    with db:
                        db.execute("UPDATE demo_management SET status='resolved' WHERE cycle_id=?", (row["cycle_id"],))
            for p in positions:
                if p.magic != MAGIC:
                    continue
                expiry = session_end(datetime.fromtimestamp(p.time, UTC))
                with db:
                    db.execute("INSERT OR IGNORE INTO prospective_demo_positions VALUES (?,?,?)",
                               (self.login, p.identifier, expiry.isoformat()))
                stored = db.execute("SELECT expires_utc FROM prospective_demo_positions WHERE account=? AND position_id=?",
                                    (self.login, p.identifier)).fetchone()
                saved = datetime.fromisoformat(stored["expires_utc"])
                emergency = saved != expiry and now >= saved
                if emergency or not (p.sl > 0 and p.tp > 0):
                    overdue.append(p)
        for p in overdue:
            self.close_position(db, p)
        with self.connection() as account:
            current = self.positions()
            self.status(db, account, current, utc_now())
            # If a required close failed, fail closed for new entries this cycle.
            overdue_ids = {p.identifier for p in overdue}
            if any(p.magic == MAGIC and p.identifier in overdue_ids for p in current):
                raise RuntimeError("Cierre pendiente: se suspenden nuevas entradas")
            return any(p.magic == MAGIC for p in current)

    def enter(self, db, cycle, symbol, side, sl, tp, received_utc):
        now = utc_now()
        if (not in_session(now) or not 0 <= (now - datetime.fromisoformat(received_utc)).total_seconds() <= 45
                or session_end(now) - now <= timedelta(seconds=30)):
            event(db, self.login, symbol, "BLOCKED", "Respuesta vencida o sesión próxima a cerrar")
            return
        try:
            with self.connection(trading=True) as account:
                emergency = self.enter_connected(db, account, cycle, symbol, side, sl, tp)
            if emergency:
                self.close_position(db, emergency)
        except RuntimeError as exc:
            event(db, self.login, symbol, "BLOCKED", str(exc))

    def enter_connected(self, db, account, cycle, symbol, side, sl, tp):
        mt5 = self.mt5
        now = utc_now()
        positions = self.positions()
        realized, blocked = self.status(db, account, positions, now)
        if blocked or not math.isfinite(account.equity) or account.equity <= 0:
            raise RuntimeError("Límite de pérdidas o equity inválido")
        if any(p.symbol == symbol or p.magic == MAGIC for p in positions):
            raise RuntimeError("Ya existe una posición del laboratorio o del símbolo")
        pending = mt5.orders_get(symbol=symbol)
        if pending is None or pending:
            raise RuntimeError("No se pudo descartar órdenes pendientes en el símbolo")
        if db.execute("""
            SELECT 1 FROM prospective_demo_entries WHERE account=? AND status IN ('sending','unconfirmed')
        """, (self.login,)).fetchone():
            raise RuntimeError("Hay una orden anterior sin confirmar; revisá el historial MT5")
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError("Símbolo demo no disponible")
        info = mt5.symbol_info(symbol)
        if not info or not (info.point > 0 and info.trade_tick_size > 0):
            raise RuntimeError("Especificaciones MT5 no disponibles")
        news = calendar_status(self.calendar, {info.currency_base, info.currency_profit}, now)
        if news:
            raise RuntimeError(news)
        tick = tick_for(mt5, symbol, now)
        rule = self.settings[symbol]
        if tick.ask - tick.bid > info.point * rule["max_spread_points"] + 1e-12:
            raise RuntimeError("Spread superior al máximo configurado")
        buy = side == "BUY"
        trade_type = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
        price = tick.ask if buy else tick.bid
        sl, tp = (round(round(level / info.trade_tick_size) * info.trade_tick_size, info.digits)
                  for level in (sl, tp))
        distance = max(info.trade_stops_level, info.trade_freeze_level) * info.point
        good = (sl < tick.bid and tp > tick.ask and min(tick.bid - sl, tp - tick.bid) >= distance if buy
                else tp < tick.bid and sl > tick.ask and min(sl - tick.ask, tick.ask - tp) >= distance)
        if not good:
            raise RuntimeError("SL/TP incompatibles con el precio actual o las distancias del broker")
        slippage_points = rule["slippage_buffer_points_per_side"]
        risk_cap = min(RISK_USD, DAILY_LIMIT_USD + min(realized, 0), account.equity * 0.0025)
        reference_volume = info.volume_min
        if reference_volume <= 0:
            raise RuntimeError("Volumen mínimo inválido")
        commission = rule["commission_usd_per_lot_roundtrip"]
        risk_per_lot = protected_loss(mt5, trade_type, symbol, reference_volume, price, sl,
                                     info.point, slippage_points, commission) / reference_volume
        volume = floor_volume(info, risk_cap / risk_per_lot)
        if volume <= 0:
            raise RuntimeError(f"El lote mínimo supera el riesgo disponible de {risk_cap:.2f} USD")
        priced_loss = protected_loss(mt5, trade_type, symbol, volume, price, sl,
                                     info.point, slippage_points, commission)
        if priced_loss > risk_cap + 1e-9:
            raise RuntimeError("Riesgo del volumen superior al límite")
        comment = f"AIT{cycle[:20]}"
        request = self.select_filling({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume, "type": trade_type,
            "price": price, "sl": sl, "tp": tp, "magic": MAGIC, "comment": comment,
            "deviation": rule["slippage_buffer_points_per_side"], "type_time": mt5.ORDER_TIME_GTC,
        }, info)
        with write_lock(db):
            if entries_blocked(db):
                raise RuntimeError("Entradas bloqueadas desde el panel")
            inserted = db.execute("""
                INSERT OR IGNORE INTO prospective_demo_entries
                (cycle_id,account,symbol,order_comment,status,updated_utc,detail)
                VALUES (?,?,?,?,'sending',?,?)
            """, (cycle, self.login, symbol, comment, now.isoformat(), f"{side} · {volume} lotes · riesgo estimado USD {priced_loss:.4f} · SL {sl} · TP {tp}"))
        if inserted.rowcount != 1:
            return
        active = mt5.account_info()
        try:
            ensure_demo(mt5, active, self.login)
            if not in_session(utc_now()) or entries_blocked(db):
                raise RuntimeError("Entradas bloqueadas o sesión cerrada")
        except RuntimeError as exc:
            self.order_status(db, cycle, "rejected", str(exc))
            return
        try:
            result = mt5.order_send(request)
        except Exception:
            self.order_status(db, cycle, "unconfirmed", "Excepción después de iniciar el envío")
            event(db, self.login, symbol, "ORDER_UNCONFIRMED", "Verificá el historial MT5")
            return
        code = getattr(result, "retcode", None)
        if code not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
            uncertain = code in (None, getattr(mt5, "TRADE_RETCODE_TIMEOUT", 10012),
                                 getattr(mt5, "TRADE_RETCODE_CONNECTION", 10031), getattr(mt5, "TRADE_RETCODE_PLACED", 10008))
            self.order_status(db, cycle, "unconfirmed" if uncertain else "rejected", f"Retcode {code}")
            event(db, self.login, symbol, "ORDER_UNCONFIRMED" if uncertain else "ORDER_REJECTED", f"Retcode {code}")
            return
        live_positions = mt5.positions_get(symbol=symbol)
        own = next((p for p in live_positions or () if p.magic == MAGIC), None)
        ident = own.identifier if own else None
        confirmed = bool(own and abs(own.sl - sl) < info.trade_tick_size / 2
                         and abs(own.tp - tp) < info.trade_tick_size / 2)
        detail = (f"{side} · {result.volume} lotes · precio {result.price} · riesgo estimado USD {priced_loss:.4f}"
                  f" · SL solicitado {sl} · TP solicitado {tp}")
        if own:
            detail += f" · SL leído {own.sl} · TP leído {own.tp}"
        self.order_status(db, cycle, "filled" if confirmed else "unconfirmed", detail, ident)
        event(db, self.login, symbol, "OPEN" if confirmed else "ORDER_UNCONFIRMED", detail)
        if own:
            with db:
                db.execute("INSERT OR IGNORE INTO prospective_demo_positions VALUES (?,?,?)",
                           (self.login, ident, session_end(now).isoformat()))
            try:
                after = protected_loss(mt5, trade_type, symbol, own.volume, own.price_open, own.sl,
                                       info.point, slippage_points, commission) if own.sl > 0 else None
            except RuntimeError:
                after = None
            if not confirmed or after is None or after > risk_cap + 1e-9:
                with db:
                    db.execute("UPDATE prospective_demo_positions SET expires_utc=? WHERE account=? AND position_id=?",
                               (now.isoformat(), self.login, ident))
                event(db, self.login, symbol, "RISK_CLOSE", "Protección o riesgo posterior al llenado fuera de límites")
                return own

    def manage(self, db, cycle, symbol, identity, action, sl, tp, received_utc):
        now = utc_now()
        if not 0 <= (now - datetime.fromisoformat(received_utc)).total_seconds() <= 45:
            return
        mt5 = self.mt5
        reserved = False
        try:
            with self.connection(trading=True):
                matches = [p for p in self.positions() if p.identifier == identity and p.magic == MAGIC and p.symbol == symbol]
                if len(matches) != 1:
                    raise RuntimeError("Ya no existe la posición propia de la propuesta")
                p = matches[0]
                request, step = self.modification(p, sl, tp, now) if action == "MODIFY" else (None, None)
                detail = json.dumps({"sl": request["sl"], "tp": request["tp"], "step": step}) if request else None
                with write_lock(db):
                    pending = db.execute("""SELECT 1 FROM demo_management WHERE account=? AND position_id=?
                        AND status IN ('sending','unconfirmed')""", (self.login, identity)).fetchone()
                    if pending:
                        raise RuntimeError("Existe una acción de gestión pendiente de reconciliar")
                    reserved = db.execute("""INSERT OR IGNORE INTO demo_management
                        (cycle_id,account,position_id,action,status,started_utc,detail)
                        VALUES (?,?,?,?,'sending',?,?)""", (cycle, self.login, identity, action, now.isoformat(), detail)).rowcount == 1
                if not reserved:
                    return
                if action == "MODIFY":
                    ensure_demo(mt5, mt5.account_info(), self.login)
                    response = mt5.order_send(request)
                    updated = mt5.positions_get(ticket=p.ticket)
                    confirmed = bool(response and response.retcode == mt5.TRADE_RETCODE_DONE and updated
                                     and abs(updated[0].sl - request["sl"]) < step / 2
                                     and abs(updated[0].tp - request["tp"]) < step / 2)
            if action == "CLOSE":
                confirmed = self.close_position(db, p)
            state = "confirmed" if confirmed else "unconfirmed"
            with db:
                db.execute("UPDATE demo_management SET status=? WHERE cycle_id=?", (state, cycle))
            event(db, self.login, symbol, action, state)
        except Exception as exc:
            if reserved:
                with db:
                    db.execute("UPDATE demo_management SET status='unconfirmed' WHERE cycle_id=?", (cycle,))
            event(db, self.login, symbol, "MANAGEMENT_BLOCKED", str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)

    def modification(self, p, sl, tp, now):
        mt5 = self.mt5
        info = mt5.symbol_info(p.symbol)
        tick = tick_for(mt5, p.symbol, now)
        if not info or not (info.point > 0 and info.trade_tick_size > 0 and p.sl > 0 and p.tp > 0):
            raise RuntimeError("Protección o especificaciones insuficientes")
        if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in (sl, tp)):
            raise RuntimeError("Precios SL/TP inválidos")
        sl, tp = (round(round(level / info.trade_tick_size) * info.trade_tick_size, info.digits)
                  for level in (sl, tp))
        distance = max(info.trade_stops_level, info.trade_freeze_level) * info.point
        if p.type == mt5.POSITION_TYPE_BUY:
            safe = sl >= p.sl and sl < tick.bid and tp > tick.ask and min(tick.bid - sl, tp - tick.bid) >= distance
        else:
            safe = sl <= p.sl and sl > tick.ask and tp < tick.bid and min(sl - tick.ask, tick.ask - tp) >= distance
        if not safe:
            raise RuntimeError("Modificar estos niveles elevaría el riesgo o incumpliría las distancias MT5")
        request = {"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket,
                   "sl": sl, "tp": tp, "magic": MAGIC}
        checked = mt5.order_check(request)
        if checked is None or checked.retcode != 0:
            raise RuntimeError("MT5 rechazó la modificación en order_check")
        return request, info.trade_tick_size

    def order_status(self, db, cycle, status, detail, position=None):
        with db:
            db.execute("""
                UPDATE prospective_demo_entries SET status=?, updated_utc=?, position_id=?, detail=? WHERE cycle_id=?
            """, (status, utc_now().isoformat(), position, detail, cycle))
