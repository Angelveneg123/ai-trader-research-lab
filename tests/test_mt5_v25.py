import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import mt5_connection as ipc


def fake():
    return Mock(ACCOUNT_TRADE_MODE_DEMO=0, initialize=Mock(return_value=True),
                account_info=Mock(return_value=SimpleNamespace(trade_mode=0,currency="USD",server="Deriv-Demo",login=123)),
                terminal_info=Mock(return_value=SimpleNamespace(connected=True)))


@pytest.mark.parametrize(("native", "expected", "attempts"), [
    (-6, "AUTHORIZATION_FAILED", 1), (-10005, "IPC_TIMEOUT", 2), (-10003, "IPC_FAILED", 2),
])
def test_classifies_native_error(monkeypatch, native, expected, attempts):
    monkeypatch.setattr(ipc.time, "sleep", lambda _: None)
    fake_mt5 = fake()
    fake_mt5.initialize.return_value = False
    fake_mt5.last_error.return_value = (native, "do not expose provider details")
    with pytest.raises(ipc.MT5Unavailable) as error:
        with ipc.connection(fake_mt5):
            pytest.fail("La conexión fallida jamás debe habilitar lecturas")
    assert error.value.code == expected
    assert error.value.native_code == native
    assert fake_mt5.initialize.call_count == attempts
    assert "do not expose" not in str(error.value)


def test_selects_path_and_recovers_once(monkeypatch, tmp_path):
    monkeypatch.setattr(ipc.time, "sleep", lambda _: None)
    path = tmp_path / "terminal64.exe"
    path.touch()
    fake_mt5 = fake()
    fake_mt5.initialize.side_effect = [False, True]
    fake_mt5.last_error.return_value = (-10005, "simulado")
    with ipc.connection(fake_mt5, executable=path, login=123):
        pass
    fake_mt5.initialize.assert_called_with(str(path), timeout=4000)
    fake_mt5.shutdown.assert_called_once()


def test_appdata_works_with_two_installations_and_explicit_override(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    program_files = tmp_path / "Program Files"
    user_terminal = appdata / "MetaTrader 5" / "terminal64.exe"
    system_terminal = program_files / "MetaTrader 5" / "terminal64.exe"
    for terminal in (user_terminal, system_terminal):
        terminal.parent.mkdir(parents=True)
        terminal.touch()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("MT5_TERMINAL_PATH", raising=False)
    monkeypatch.delenv("MT5_TIMEOUT_MS", raising=False)

    assert ipc.installations() == [user_terminal, system_terminal]
    assert ipc.terminal_path() == user_terminal.resolve()
    fake_mt5 = fake()
    with ipc.connection(fake_mt5, load_env=False):
        fake_mt5.initialize.assert_called_once_with(str(user_terminal.resolve()), timeout=4000)
        fake_mt5.order_send.assert_not_called()

    monkeypatch.setenv("MT5_TERMINAL_PATH", str(system_terminal))
    assert ipc.terminal_path() == system_terminal.resolve()
    assert ipc.terminal_path(user_terminal) == user_terminal.resolve()


def test_wrong_demo_server_and_disconnected(monkeypatch):
    demo = fake()
    monkeypatch.setenv("MT5_EXPECTED_SERVER", "Deriv-Demo")
    demo.account_info.return_value.server = "OtroBroker-Demo"
    with pytest.raises(ipc.MT5Unavailable) as error:
        with ipc.connection(demo):
            pytest.fail("Servidor distinto")
    assert error.value.code == "SERVER_MISMATCH"
    demo.terminal_info.return_value.connected = False
    with pytest.raises(ipc.MT5Unavailable) as error:
        with ipc.connection(demo):
            pytest.fail("Terminal desconectado")
    assert error.value.code == "TERMINAL_DISCONNECTED"
