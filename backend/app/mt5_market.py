from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import math
from threading import Lock
from time import monotonic

from .market_symbols import BASE_SYMBOLS, valid_market_symbol
from .mt5_connection import MT5Unavailable, connection

SYMBOLS = BASE_SYMBOLS
TIMEFRAMES = {"M5": 5, "M15": 15, "H1": 16385}
SECONDS = {"M5": 300, "M15": 900, "H1": 3600}
READ_RETRY_SECONDS = 15
STATUS_TTL_SECONDS = 6
_read_gate = Lock()
_status_sample = None


def session_status(account, terminal):
    return {
        "connected": True, "demo": True, "currency": account.currency, "server": account.server,
        "terminal_trade_allowed": bool(terminal.trade_allowed and not getattr(terminal, "tradeapi_disabled", True)),
        "account_trade_allowed": bool(account.trade_allowed and account.trade_expert),
        "balance": float(account.balance), "equity": float(account.equity),
        "error": None, "error_code": None, "mt5_code": None,
    }


def unavailable_status(exc):
    return {"connected": False, "demo": False, "currency": None, "server": None, "balance": None,
            "equity": None, "terminal_trade_allowed": False, "account_trade_allowed": False,
            "error": str(exc), "error_code": exc.code, "mt5_code": exc.native_code}


@contextmanager
def read_session():
    """Share one read attempt among FastAPI and its research worker."""
    global _status_sample
    if not _read_gate.acquire(blocking=False):
        raise MT5Unavailable("TERMINAL_BUSY", "MT5 está atendiendo otra lectura.")
    try:
        sample = _status_sample
        if sample:
            checked, status = sample
            if not status["connected"] and monotonic() - checked < READ_RETRY_SECONDS:
                raise MT5Unavailable(status["error_code"], status["error"], status["mt5_code"])
        with ExitStack() as stack:
            try:
                mt5, account, terminal = stack.enter_context(connection(retries=0))
            except MT5Unavailable as exc:
                # A separate process may briefly own the IPC lock. Do not cache its busy state.
                if exc.code != "TERMINAL_BUSY":
                    _status_sample = (monotonic(), unavailable_status(exc))
                raise
            _status_sample = (monotonic(), session_status(account, terminal))
            yield mt5
    finally:
        _read_gate.release()


def get_mt5_status(executable=None, retries=0):
    if executable is not None or retries:
        try:
            with connection(executable=executable, retries=retries) as (_, account, terminal):
                return session_status(account, terminal)
        except MT5Unavailable as exc:
            return unavailable_status(exc)
    sample = _status_sample
    if sample:
        checked, status = sample
        ttl = STATUS_TTL_SECONDS if status["connected"] else READ_RETRY_SECONDS
        if monotonic() - checked < ttl:
            return status.copy()
    try:
        with read_session():
            return _status_sample[1].copy()
    except MT5Unavailable as exc:
        return unavailable_status(exc)


def closed_candles(mt5, symbol, timeframe, limit, cutoff=None):
    if not mt5.symbol_select(symbol, True):
        raise MT5Unavailable("SYMBOL_UNAVAILABLE", f"Símbolo no disponible: {symbol}")
    rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, f"TIMEFRAME_{timeframe}", TIMEFRAMES[timeframe]), 1, limit)
    candles = []
    now = int(datetime.now(timezone.utc).timestamp())
    ceiling = min(now, cutoff) if cutoff is not None else now
    for rate in rates if rates is not None else ():
        ts = int(rate["time"])
        prices = [float(rate[key]) for key in ("open", "high", "low", "close")]
        if ts + SECONDS[timeframe] > ceiling or not all(math.isfinite(v) for v in prices):
            continue
        op, hi, lo, cl = prices
        if 0 < lo <= min(op, cl) <= max(op, cl) <= hi:
            candles.append({"time": ts, "open": op, "high": hi, "low": lo, "close": cl, "volume": int(rate["tick_volume"])})
    if not candles:
        raise MT5Unavailable("NO_CLOSED_CANDLES", "MT5 no entregó velas cerradas válidas.")
    candles.sort(key=lambda c: c["time"])
    return candles


def get_candles(symbol="EURUSD", timeframe="M5", limit=200, cutoff=None, *, executable=None, include_quote=False):
    if not valid_market_symbol(symbol) or timeframe not in TIMEFRAMES or not 1 <= limit <= 1000:
        raise ValueError("Parámetros de mercado inválidos")

    def read_market(mt5):
        candles = closed_candles(mt5, symbol, timeframe, limit, cutoff)
        value = {"symbol": symbol, "timeframe": timeframe, "source": "deriv_mt5",
                 "closed_candles_only": True, "count": len(candles), "candles": candles,
                 "fetched_at": datetime.now(timezone.utc).isoformat()}
        if include_quote:
            value["quote"] = quote_in_session(mt5, symbol)
        return value

    if executable is not None:
        with connection(executable=executable, retries=0) as (mt5, _, _):
            return read_market(mt5)
    with read_session() as mt5:
        return read_market(mt5)


def quote_in_session(mt5, symbol):
    tick, info = mt5.symbol_info_tick(symbol), mt5.symbol_info(symbol)
    if not tick or not info or not 0 < tick.bid <= tick.ask or not info.point > 0:
        return None
    if not all(math.isfinite(value) for value in (tick.bid, tick.ask, info.point)):
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    return {"bid": float(tick.bid), "ask": float(tick.ask),
            "spread_points": round((tick.ask - tick.bid) / info.point, 3),
            "stale": not -5 <= now - int(tick.time) <= 120,
            "sampled_at": now, "tick_time": int(tick.time),
            "kind": "current_snapshot_not_historical"}


def get_quote_snapshot(symbol):
    if not valid_market_symbol(symbol):
        raise ValueError("Símbolo no permitido")
    try:
        with read_session() as mt5:
            return quote_in_session(mt5, symbol) if mt5.symbol_select(symbol, True) else None
    except MT5Unavailable:
        return None
