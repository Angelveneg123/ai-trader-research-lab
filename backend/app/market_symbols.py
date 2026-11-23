import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
BASE_SYMBOLS = ("XAUUSD", "EURUSD", "USDJPY")
MICRO_SYMBOLS = ("EURUSDmicro", "USDJPYmicro", "XAUUSDmicro")


def load_settings():
    load_dotenv(ENV_PATH, override=False, encoding="utf-8-sig")


def live_symbols():
    load_settings()
    configured = os.getenv("MT5_SYMBOLS") or ",".join(MICRO_SYMBOLS)
    return tuple(dict.fromkeys(s.strip() for s in configured.split(",") if s.strip()))


def valid_market_symbol(symbol):
    return symbol in (*BASE_SYMBOLS, *MICRO_SYMBOLS, *live_symbols())


def settings_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else ENV_PATH.parent / path
