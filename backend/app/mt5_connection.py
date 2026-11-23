"""Shared, bounded connection to an already configured MT5 demo terminal."""
import importlib
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .market_symbols import load_settings


class MT5Unavailable(RuntimeError):
    def __init__(self, code, message, native_code=None):
        super().__init__(message)
        self.code = code
        self.native_code = native_code


def appdata_terminal():
    root = os.getenv("APPDATA")
    if root:
        path = Path(root) / "MetaTrader 5" / "terminal64.exe"
        if path.is_file():
            return path
    return None


def installations():
    user_terminal = appdata_terminal()
    candidates = [user_terminal] if user_terminal else []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.getenv(variable)
        if not root:
            continue
        for folder in ("MetaTrader 5", "Deriv MT5", "Deriv MetaTrader 5"):
            path = Path(root) / folder / "terminal64.exe"
            if path.is_file() and path not in candidates:
                candidates.append(path)
    return candidates


def terminal_path(override=None):
    path = override or os.getenv("MT5_TERMINAL_PATH")
    if path:
        selected = Path(os.path.expandvars(str(path))).expanduser()
        if selected.name.casefold() != "terminal64.exe" or not selected.is_file():
            raise MT5Unavailable("INVALID_TERMINAL_PATH", "Seleccioná el terminal64.exe de tu instalación MT5.")
        return selected.resolve()
    user_terminal = appdata_terminal()
    if user_terminal:
        return user_terminal.resolve()
    candidates = installations()
    if len(candidates) > 1:
        raise MT5Unavailable("AMBIGUOUS_TERMINAL", "Hay varios terminales. Configurá MT5_TERMINAL_PATH.")
    return candidates[0].resolve() if candidates else None


def backend_module():
    try:
        return importlib.import_module("MetaTrader5")
    except (ImportError, OSError) as exc:
        raise MT5Unavailable("MT5_MODULE_UNAVAILABLE", "MetaTrader5 no está disponible. Usá el terminal y Python de Windows.") from exc


@contextmanager
def ipc_lock():
    path = Path(tempfile.gettempdir()) / "ai_trader_mt5_ipc.sqlite3"
    db = sqlite3.connect(path, timeout=2)
    try:
        try:
            db.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise MT5Unavailable("TERMINAL_BUSY", "MT5 ocupado por otro proceso. Volvé a intentar.") from exc
        yield
    finally:
        db.close()


def native_error(mt5):
    result = mt5.last_error()
    code = result[0] if isinstance(result, (tuple, list)) and result and type(result[0]) is int else None
    if code == -6:
        return MT5Unavailable("AUTHORIZATION_FAILED", "Iniciá sesión manualmente en la cuenta Deriv demo y verificá el servidor.", code)
    if code in (-10000, -10001, -10002, -10003, -10005):
        return MT5Unavailable("IPC_TIMEOUT" if code == -10005 else "IPC_FAILED",
                              "No respondió el canal IPC. Verificá el terminal, su ruta y que Python use la misma sesión de Windows.", code)
    return MT5Unavailable("INITIALIZATION_FAILED", "MT5 no pudo inicializar la conexión.", code)


def ensure_demo(mt5, account, login=None):
    if not account:
        raise MT5Unavailable("NO_ACCOUNT", "MT5 está abierto, pero falta una cuenta conectada.")
    if account.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        raise MT5Unavailable("ACCOUNT_NOT_DEMO", "Se requiere una cuenta MT5 demo.")
    if account.currency != "USD":
        raise MT5Unavailable("ACCOUNT_NOT_USD", "La cuenta demo debe estar en USD.")
    server = str(getattr(account, "server", "")).strip()
    expected = os.getenv("MT5_EXPECTED_SERVER", "").strip()
    if "deriv" not in server.casefold() or (expected and server.casefold() != expected.casefold()):
        raise MT5Unavailable("SERVER_MISMATCH", "El servidor no coincide con la cuenta Deriv demo configurada.")
    if login is not None and account.login != login:
        raise MT5Unavailable("ACCOUNT_MISMATCH", "La cuenta activa no coincide con el login demo configurado.")


def initialize_timeout(timeout_ms=None):
    value = timeout_ms if timeout_ms is not None else os.getenv("MT5_TIMEOUT_MS", "4000")
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = 0
    if not 1000 <= timeout <= 120000:
        raise MT5Unavailable("INVALID_TIMEOUT", "MT5_TIMEOUT_MS debe estar entre 1000 y 120000 milisegundos.")
    return timeout


@contextmanager
def connection(mt5=None, *, login=None, trading=False, executable=None, retries=1,
               timeout_ms=None, load_env=True):
    if load_env:
        load_settings()
    timeout = initialize_timeout(timeout_ms)
    mt5 = backend_module() if mt5 is None else mt5
    selected = terminal_path(executable)
    with ipc_lock():
        for index in range(retries + 1):
            args = (str(selected),) if selected else ()
            if mt5.initialize(*args, timeout=timeout):
                break
            error = native_error(mt5)
            if error.code not in ("IPC_TIMEOUT", "IPC_FAILED") or index >= retries:
                raise error
            time.sleep(0.30)
        try:
            terminal = mt5.terminal_info()
            if not terminal or not terminal.connected:
                raise MT5Unavailable("TERMINAL_DISCONNECTED", "El terminal MT5 está desconectado del servidor.")
            account = mt5.account_info()
            ensure_demo(mt5, account, login)
            if trading and (not terminal.trade_allowed or getattr(terminal, "tradeapi_disabled", True)
                            or not account.trade_allowed or not account.trade_expert):
                raise MT5Unavailable("TRADING_NOT_ALLOWED", "MT5 bloquea el trading algorítmico o el acceso de Python.")
            yield mt5, account, terminal
        finally:
            mt5.shutdown()
