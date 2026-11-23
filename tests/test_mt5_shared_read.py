from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import mt5_market as market


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(market, "_status_sample", None)


def test_failed_handshake_backs_off_across_other_reads(monkeypatch):
    clock = Mock(return_value=100)
    terminal = Mock(side_effect=market.MT5Unavailable("IPC_TIMEOUT", "Tiempo agotado", -10005))
    monkeypatch.setattr(market, "monotonic", clock)
    monkeypatch.setattr(market, "connection", terminal)

    assert market.get_mt5_status()["mt5_code"] == -10005
    for symbol in ("EURUSDmicro", "USDJPYmicro", "XAUUSDmicro"):
        with pytest.raises(market.MT5Unavailable, match="Tiempo agotado"):
            market.get_candles(symbol)
    assert market.get_quote_snapshot("EURUSDmicro") is None
    assert terminal.call_count == 1

    clock.return_value = 100 + market.READ_RETRY_SECONDS
    assert not market.get_mt5_status()["connected"]
    assert terminal.call_count == 2


def connected_sample():
    now = int(datetime.now(timezone.utc).timestamp())
    terminal = Mock(TIMEFRAME_M5=5)
    terminal.symbol_select.return_value = True
    terminal.copy_rates_from_pos.return_value = [
        {"time": now - 600, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.1, "tick_volume": 2},
    ]
    terminal.symbol_info_tick.return_value = SimpleNamespace(bid=1.1, ask=1.1001, time=now)
    terminal.symbol_info.return_value = SimpleNamespace(point=.00001)
    account = SimpleNamespace(currency="USD", server="Deriv-Demo", trade_allowed=False,
                              trade_expert=False, balance=100, equity=100)
    info = SimpleNamespace(trade_allowed=False, tradeapi_disabled=True)

    @contextmanager
    def connection(**_):
        yield terminal, account, info

    return terminal, Mock(side_effect=connection)


def test_chart_reads_candles_and_quote_in_same_session(monkeypatch):
    terminal, connection = connected_sample()
    monkeypatch.setattr(market, "connection", connection)
    value = market.get_candles("EURUSDmicro", include_quote=True)
    assert value["count"] == 1 and value["quote"]["spread_points"] == 10
    assert market.get_mt5_status()["connected"]
    assert connection.call_count == 1
    terminal.order_send.assert_not_called()


def test_other_callers_do_not_open_a_second_session(monkeypatch):
    _, connection = connected_sample()
    monkeypatch.setattr(market, "connection", connection)
    with market.read_session():
        with pytest.raises(market.MT5Unavailable) as err:
            with market.read_session():
                pytest.fail("Se abrió una segunda sesión")
        assert err.value.code == "TERMINAL_BUSY"
        assert market.get_mt5_status()["connected"]
        assert connection.call_count == 1


def test_observer_reads_three_timeframes_in_one_session(tmp_path, monkeypatch):
    from app import research

    terminal, connection = connected_sample()
    terminal.TIMEFRAME_M15 = 15
    terminal.TIMEFRAME_H1 = 16385
    monkeypatch.setattr(market, "connection", connection)
    monkeypatch.setattr(research, "DB", tmp_path/"observations.sqlite3")

    now = int(datetime.now(timezone.utc).timestamp())

    def rates(symbol, tf, offset, limit):
        offset_seconds = {5: 300, 15: 900, 16385: 3600}[tf]
        end = now // offset_seconds * offset_seconds
        return [{"time": end - i * offset_seconds, "open": 1.1, "high": 1.11, "low": 1.09,
                 "close": 1.1, "tick_volume": 22} for i in reversed(range(offset, offset + limit))]

    terminal.copy_rates_from_pos.side_effect = rates
    assert research.analyze_symbol("EURUSDmicro")
    assert connection.call_count == 1
    assert terminal.copy_rates_from_pos.call_count == 3
