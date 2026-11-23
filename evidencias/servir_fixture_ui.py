"""Servidor local de evidencia. Datos totalmente simulados, cero red externa."""
import os
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import prospectivo_v22 as runner
from app.prospective_store import connect, update_runtime

NOW = datetime(2026, 11, 20, 13, 0, 12, tzinfo=timezone.utc)
SYMBOL = "EURUSDmicro"
MARKETS = (SYMBOL, "USDJPYmicro", "XAUUSDmicro")


def rates(symbol, period, offset, size):
    step = {5: 300, 15: 900, 16385: 3600}[period]
    end = int(NOW.timestamp()) // step * step
    return [{"time": end - i * step, "open": 1.101 - i * .000014, "close": 1.101 - i * .000013,
             "high": 1.102, "low": 1.097, "tick_volume": 101} for i in reversed(range(offset, offset + size))]


def main():
    with TemporaryDirectory(prefix="simulado_aitrader_") as temp:
        appdata = Path(temp) / "AppData" / "Roaming"
        program_files = Path(temp) / "Program Files"
        terminal = appdata / "MetaTrader 5" / "terminal64.exe"
        system_terminal = program_files / "MetaTrader 5" / "terminal64.exe"
        for executable in (terminal, system_terminal):
            executable.parent.mkdir(parents=True)
            executable.touch()
        os.environ.update(PROSPECTIVE_DB=str(Path(temp) / "prospective.sqlite3"))
        os.environ.update(RESEARCH_DB=str(Path(temp) / "research.sqlite3"), GEMINI_API_KEY="fixture-only",
                          OPENAI_ENABLED="0", TELEGRAM_ENABLED="0", MT5_SYMBOLS=",".join(MARKETS))
        os.environ.update(APPDATA=str(appdata), ProgramFiles=str(program_files))
        os.environ.pop("MT5_TERMINAL_PATH", None)
        mt5 = Mock(TIMEFRAME_M5=5, TIMEFRAME_M15=15, TIMEFRAME_H1=16385, ACCOUNT_TRADE_MODE_DEMO=0)

        def initialize(path, *, timeout):
            assert Path(path) == terminal.resolve(), "El arranque eligió otra instalación de MT5"
            return True

        mt5.initialize.side_effect = initialize
        mt5.account_info.return_value = SimpleNamespace(
            login=123, currency="USD", server="Deriv-Demo-FIXTURE", trade_mode=0,
            balance=100, equity=100, trade_allowed=False, trade_expert=False)
        mt5.terminal_info.return_value = SimpleNamespace(connected=True, trade_allowed=False, tradeapi_disabled=True)
        mt5.symbol_select.return_value = True
        mt5.symbol_info.return_value = SimpleNamespace(digits=5, point=.00001, trade_stops_level=20,
                                                       trade_contract_size=1000, currency_profit="USD")
        mt5.copy_rates_from_pos.side_effect = rates
        mt5.positions_get.return_value = ()
        mt5.order_send.side_effect = AssertionError("La prueba en observación no puede enviar órdenes")
        mt5.symbol_info_tick.return_value = SimpleNamespace(bid=1.1010, ask=1.10108, time=int(NOW.timestamp()))
        sys.modules["MetaTrader5"] = mt5
        runner.utc_now = lambda: NOW
        runner.call_provider = lambda *args: ({"action": "WAIT", "reason": "Fixture de interfaz y SQLite",
                                              "sl": None, "tp": None}, (552, 36))
        with closing(connect()) as db:
            for symbol in MARKETS:
                print("SIMULADA", runner.run_cycle(db, symbol, ["gemini"], {"gemini": "gemini-3.1-flash-lite"}, .05), flush=True)
            update_runtime(db, "dry-run", "gemini")
            print(dict(db.execute("SELECT cycle_id,provider,received_utc,action FROM prospective_decisions").fetchone()), flush=True)
        if os.getenv("UI_TEST_DISCONNECTED") == "1":
            mt5.initialize.side_effect = None
            mt5.initialize.return_value = False
            mt5.last_error.return_value = (-10005, "IPC timeout")
        from iniciar_laboratorio import main as launch

        try:
            return launch(["--sin-navegador"])
        finally:
            mt5.order_send.assert_not_called()


if __name__ == "__main__":
    sys.exit(main())
