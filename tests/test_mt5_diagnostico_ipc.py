import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import diagnosticar_mt5 as diagnostic
from app import mt5_connection as ipc


def test_env_warnings_show_line_only(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("DEMO_FIXTURE=secret-example\n# comentario\nesta linea esta mal\n", encoding="utf-8-sig")
    monkeypatch.setattr(diagnostic, "ENV_PATH", env)
    monkeypatch.setattr(sys, "argv", ["diagnosticar_mt5.py", "--solo-env"])
    connect = Mock()
    monkeypatch.setattr(diagnostic, "connection", connect)
    assert diagnostic.main() == 4
    payload = capsys.readouterr().out
    assert json.loads(payload)["env"] == {"estado": "invalido", "lineas_invalidas": [3]}
    assert "secret-example" not in payload
    assert "esta linea esta mal" not in payload
    connect.assert_not_called()


def test_read_only_uses_single_session_and_skips_dotenv(tmp_path, monkeypatch, capsys):
    executable = tmp_path / "terminal64.exe"
    executable.touch()
    monkeypatch.setattr(sys, "argv", ["diagnosticar_mt5.py", "--sin-env", "--terminal", str(executable)])
    load = Mock()
    monkeypatch.setattr(ipc, "load_settings", load)
    monkeypatch.setattr(diagnostic, "load_settings", load)
    monkeypatch.delenv("MT5_EXPECTED_SERVER", raising=False)
    mt5 = Mock(ACCOUNT_TRADE_MODE_DEMO=0, TIMEFRAME_M5=5)
    mt5.initialize.return_value = True
    mt5.symbol_select.return_value = True
    mt5.account_info.return_value = SimpleNamespace(
        trade_mode=0, currency="USD", server="Deriv-Demo", trade_allowed=False, trade_expert=False,
        balance=100, equity=100,
    )
    mt5.terminal_info.return_value = SimpleNamespace(connected=True, trade_allowed=False)
    ts = int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()) // 300 * 300
    mt5.copy_rates_from_pos.return_value = [
        dict(time=ts, open=1.1, high=1.2, low=1.08, close=1.11, tick_volume=1),
    ]
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5)
    assert diagnostic.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["env"]["estado"] == "omitido"
    assert output["vela"]["simbolo"] == "EURUSDmicro"
    mt5.initialize.assert_called_once_with(str(executable), timeout=60000)
    mt5.shutdown.assert_called_once()
    mt5.order_send.assert_not_called()
    load.assert_not_called()


def test_app_timeout_configured_by_local_environment(monkeypatch):
    monkeypatch.setenv("MT5_TIMEOUT_MS", "15000")
    assert ipc.initialize_timeout() == 15000
    assert ipc.initialize_timeout(60000) == 60000
    monkeypatch.setenv("MT5_TIMEOUT_MS", "invalido")
    with pytest.raises(ipc.MT5Unavailable, match="milisegundos"):
        ipc.initialize_timeout()
