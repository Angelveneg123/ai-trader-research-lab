import json
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import prospectivo_v22 as runner
from app import demo_execution as demo
from app import prospective_outcomes as outcomes
from app import prospective_store as store

NOW = datetime(2026, 11, 20, 13, 0, 12, tzinfo=timezone.utc)
SYMBOL = "EURUSDmicro"


@pytest.fixture
def journal(tmp_path):
    with closing(store.connect(tmp_path / "research.db")) as db:
        yield db


@pytest.fixture
def mt5(monkeypatch):
    mt5 = Mock()
    constants = {
        "ACCOUNT_TRADE_MODE_DEMO": 0, "TIMEFRAME_M5": 5, "TIMEFRAME_M15": 15, "TIMEFRAME_H1": 60,
        "SYMBOL_TRADE_EXECUTION_REQUEST": 0, "SYMBOL_TRADE_EXECUTION_INSTANT": 1,
        "SYMBOL_TRADE_EXECUTION_MARKET": 2, "ORDER_FILLING_FOK": 0, "ORDER_FILLING_IOC": 1,
        "TRADE_ACTION_DEAL": 1, "TRADE_ACTION_SLTP": 6, "ORDER_TIME_GTC": 0, "ORDER_TYPE_BUY": 0, "ORDER_TYPE_SELL": 1,
        "POSITION_TYPE_BUY": 0, "TRADE_RETCODE_DONE": 10009, "TRADE_RETCODE_DONE_PARTIAL": 10010,
        "DEAL_ENTRY_IN": 0, "COPY_TICKS_INFO": 1,
    }
    mt5.configure_mock(**constants)
    mt5.initialize.return_value = True
    mt5.account_info.return_value = SimpleNamespace(login=123, currency="USD", trade_mode=0, trade_allowed=True,
                                                       trade_expert=True, balance=100, equity=100, server="Deriv-Demo")
    mt5.terminal_info.return_value = SimpleNamespace(connected=True, trade_allowed=True, tradeapi_disabled=False)
    mt5.symbol_select.return_value = True
    mt5.symbol_info.return_value = SimpleNamespace(
        digits=5, point=0.00001, trade_tick_size=0.00001, trade_stops_level=10, trade_freeze_level=3,
        trade_contract_size=1000, currency_base="EUR", currency_profit="USD", volume_min=0.1, volume_max=100,
        volume_step=0.1, filling_mode=1, trade_exemode=2,
    )
    mt5.symbol_info_tick.return_value = SimpleNamespace(bid=1.1, ask=1.10008, time=int(NOW.timestamp()))
    mt5.positions_get.return_value = ()
    mt5.orders_get.return_value = ()
    mt5.history_deals_get.return_value = ()
    mt5.order_check.return_value = SimpleNamespace(retcode=0)
    mt5.order_calc_profit.side_effect = lambda _type, _symbol, vol, entry, exit: (exit - entry) * vol * 1000

    def rates(_symbol, tf, _start, size):
        seconds = tf * 60
        current = int(NOW.timestamp()) // seconds * seconds
        return [{"time": current - i * seconds, "open": 1.1, "high": 1.11, "low": 1.09,
                 "close": 1.1, "tick_volume": 42} for i in reversed(range(size))]

    mt5.copy_rates_from_pos.side_effect = rates
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5)
    monkeypatch.setattr(runner, "utc_now", lambda: NOW)
    monkeypatch.setattr(demo, "utc_now", lambda: NOW)
    return mt5


def test_mt5_to_two_providers_and_daily_cost(journal, mt5, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "simulated")
    monkeypatch.setenv("OPENAI_API_KEY", "simulated")
    monkeypatch.setenv("OPENAI_ENABLED", "1")
    seen = []

    def http(url, headers, payload):
        seen.append(payload)
        response = '{"action":"BUY","reason":"Prueba","hypothesis":"ruptura","invalidation":"cierre contrario","horizon_m5":4,"sl":1.0998,"tp":1.101}'
        if "googleapis" in url:
            return {"usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 80, "thoughtsTokenCount": 20},
                    "candidates": [{"content": {"parts": [{"text": response}]}}]}
        return {"usage": {"prompt_tokens": 800, "completion_tokens": 100},
                "choices": [{"message": {"content": response}}]}

    monkeypatch.setattr(runner, "request_json", http)
    models = {"gemini": "gemini-3.1-flash-lite", "openai": "gpt-5.4-mini"}
    for _ in range(2):
        runner.run_cycle(journal, SYMBOL, models, models, .05)
    assert len(seen) == 2
    assert seen[0]["contents"][0]["parts"][0]["text"].split("\n", 1)[1] == seen[1]["messages"][1]["content"]
    cycle = journal.execute("SELECT * FROM prospective_cycles").fetchone()
    ctx = json.loads(cycle["context_json"])
    assert datetime.fromisoformat(cycle["m5_closed_utc"]) == NOW.replace(second=0)
    assert ctx["candles"]["M5"][-1]["t"] + 300 == int(NOW.replace(second=0).timestamp())
    assert all(r["received_utc"] == NOW.isoformat() for r in journal.execute("SELECT * FROM prospective_decisions"))
    today = store.budget(journal, "2026-11-20")
    assert today["gemini"]["spent"] == pytest.approx(.00035)
    assert today["openai"]["spent"] == pytest.approx(.00105)
    assert today["gemini"]["reserved"] == 0


def test_graceful_provider_failure_does_not_repeat(journal, mt5, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "simulated")
    failure = Mock(side_effect=RuntimeError("HTTP 500"))
    monkeypatch.setattr(runner, "request_json", failure)
    for _ in range(2):
        runner.run_cycle(journal, SYMBOL, ["gemini"], {"gemini": "gemini-3.1-flash-lite"}, .05)
    assert failure.call_count == 1
    assert journal.execute("SELECT status FROM prospective_attempts").fetchone()[0] == "error"
    assert journal.execute("SELECT COUNT(*) FROM prospective_errors").fetchone()[0] == 1
    assert store.budget(journal, "2026-11-20")["gemini"]["reserved"] > 0
    assert store.budget(journal, "2026-11-21")["gemini"]["reserved"] == 0
    assert store.budget(journal)["gemini"]["reserved"] > 0


def test_cap_total_not_reset_daily(journal):
    assert store.claim(journal, "one", "gemini", NOW, 2.49) == "reserved"
    assert store.claim(journal, "two", "gemini", NOW, .02) == "presupuesto acumulado insuficiente"
    assert store.claim(journal, "one", "openai", NOW, 2.49) == "reserved"
    tomorrow = NOW + timedelta(days=3)
    assert store.claim(journal, "two", "gemini", tomorrow, .02) == "presupuesto acumulado insuficiente"


def test_outside_session_and_live_account_are_blocked(journal, mt5, monkeypatch):
    monkeypatch.setattr(runner, "utc_now", lambda: NOW.replace(hour=16))
    runner.run_cycle(journal, SYMBOL, ["gemini"], {}, .05)
    mt5.initialize.assert_not_called()
    mt5.account_info.return_value.trade_mode = 2
    with pytest.raises(RuntimeError, match="demo"):
        runner.collect(SYMBOL)


def test_evaluate_only_post_response_ticks_with_costs():
    row = {"received_utc": NOW.isoformat(), "symbol": SYMBOL, "action": "BUY", "sl": 1.0998, "tp": 1.1005, "valid": 1}
    ctx = {"point": .00001, "pip_size": .0001, "contract_size": 1000, "quote_currency": "USD",
           "simulation": {"commission": .05, "slippage_points": 1, "source": "test"}}
    base = int(NOW.timestamp() * 1000)
    ticks = [(base - 1, 1.0995, 1.0996), (base + 5_001, 1.1000, 1.10008), (base + 6000, 1.1005, 1.1006)]
    result = outcomes.evaluate(row, ctx, ticks, [t[0] for t in ticks], store.session_end(NOW))
    assert result[0] == "TP"
    assert result[3] == pytest.approx(1.10009)
    assert result[5] == pytest.approx(3.5)
    assert result[6] == pytest.approx(1.6)


def executor(mt5, tmp_path, event=False):
    news = tmp_path / "calendar.json"
    news.write_text(json.dumps({
        "coverage_verified": True, "currencies": ["EUR", "USD"], "source": "fixture",
        "retrieved_utc": NOW.isoformat(), "coverage_start_utc": (NOW - timedelta(hours=2)).isoformat(),
        "coverage_end_utc": (NOW + timedelta(hours=4)).isoformat(),
        "events": ([{"at_utc": NOW.isoformat(), "currency": "USD", "impact": "high", "title": "CPI"}] if event else []),
    }))
    settings = {SYMBOL: {"commission_usd_per_lot_roundtrip": 0, "max_spread_points": 12,
                         "slippage_buffer_points_per_side": 2}}
    return demo.DemoExecutor(123, "gemini", settings, news, mt5)


def test_demo_entry_risk_and_session_keeps_protected_position(journal, mt5, tmp_path, monkeypatch):
    engine = executor(mt5, tmp_path)
    position = SimpleNamespace(ticket=42, identifier=42, magic=demo.MAGIC, volume=.7, price_open=1.10008,
                               sl=1.0998, tp=1.101, type=0, symbol=SYMBOL, time=int(NOW.timestamp()),
                               profit=0, swap=0)
    mt5.positions_get.side_effect = [(), (position,)]
    mt5.order_send.return_value = SimpleNamespace(retcode=10009, volume=.7, price=1.10008, deal=10)
    engine.enter(journal, "cycle", SYMBOL, "BUY", 1.0998, 1.101, NOW.isoformat())
    order = mt5.order_send.call_args.args[0]
    assert order["volume"] == .7
    assert (order["sl"], order["tp"]) == (1.0998, 1.101)
    assert journal.execute("SELECT status FROM prospective_demo_entries").fetchone()[0] == "filled"
    mt5.positions_get.side_effect = None
    mt5.positions_get.return_value = (position,)
    when = store.session_end(NOW)
    monkeypatch.setattr(demo, "utc_now", lambda: when)
    mt5.symbol_info_tick.return_value.time = int(when.timestamp())
    assert engine.maintain(journal)
    assert mt5.order_send.call_count == 1
    engine.enter(journal, "out", SYMBOL, "BUY", 1.0998, 1.101, when.isoformat())
    assert mt5.order_send.call_count == 1


def test_news_daily_loss_and_wrong_account_block_entries(journal, mt5, tmp_path):
    engine = executor(mt5, tmp_path, event=True)
    engine.enter(journal, "news", SYMBOL, "BUY", 1.0998, 1.101, NOW.isoformat())
    assert "CPI" in journal.execute("SELECT detail FROM prospective_demo_events").fetchone()[0]
    loss = SimpleNamespace(magic=demo.MAGIC, ticket=1, entry=1, position_id=45, profit=-.98,
                           commission=-.02, fee=0, swap=0, time=int(NOW.timestamp()), symbol=SYMBOL, reason=4, volume=.1, price=1.09)
    mt5.history_deals_get.return_value = (loss,)
    engine.enter(journal, "loss", SYMBOL, "BUY", 1.0998, 1.101, NOW.isoformat())
    assert journal.execute("SELECT loss_blocked FROM prospective_demo_days").fetchone()[0] == 1
    mt5.history_deals_get.return_value = ()
    engine.enter(journal, "still-locked", SYMBOL, "BUY", 1.0998, 1.101, NOW.isoformat())
    mt5.account_info.return_value.trade_mode = 2
    engine.enter(journal, "live", SYMBOL, "BUY", 1.0998, 1.101, NOW.isoformat())
    mt5.order_send.assert_not_called()


def test_telegram_report_written_and_deduplicated(journal, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setenv("TELEGRAM_ENABLED", "1")
    monkeypatch.setattr(outcomes, "utc_now", lambda: NOW.replace(hour=16, minute=5))
    request = Mock(return_value={"ok": True})
    monkeypatch.setattr(runner, "request_json", request)
    outcomes.finish_sessions(journal)
    outcomes.finish_sessions(journal)
    assert request.call_count == 1
    assert journal.execute("SELECT telegram_status FROM prospective_reports").fetchone()[0] == "sent"


def test_session_settlement_and_dashboard_api(journal, mt5, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("GEMINI_API_KEY", "simulated")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    path = journal.execute("PRAGMA database_list").fetchone()["file"]
    monkeypatch.setenv("PROSPECTIVE_DB", path)
    monkeypatch.setattr(runner, "call_provider", lambda *args: (
        {"action": "BUY", "reason": "test", "sl": 1.0998, "tp": 1.1005,
         "hypothesis": "ruptura", "invalidation": "cierre contrario", "horizon_m5": 4}, (200, 40),
    ))
    runner.run_cycle(journal, SYMBOL, ["gemini"], {"gemini": "gemini-3.1-flash-lite"}, .05)
    monkeypatch.setattr(outcomes, "utc_now", lambda: NOW.replace(hour=16, minute=3))
    stamp = int(NOW.timestamp() * 1000)
    mt5.copy_ticks_range.return_value = [
        {"time_msc": stamp + 5100, "bid": 1.1, "ask": 1.10008},
        {"time_msc": stamp + 6100, "bid": 1.1005, "ask": 1.10059},
    ]
    outcomes.finish_sessions(journal)
    outcomes.finish_sessions(journal)
    assert mt5.copy_ticks_range.call_count == 1
    response = TestClient(app).get("/api/prospective", params={"symbol": SYMBOL})
    assert response.status_code == 200
    data = response.json()
    assert data["decisions"] == 1 and data["recent"][0]["outcome"] == "TP"
    assert data["recent"][0]["net_pips"] == pytest.approx(4)
    assert SYMBOL in data["reports"][0]["body"]


def test_diagnostic_only_no_trade_or_prospective_cycle(journal, mt5, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "simulated")
    monkeypatch.setattr(runner, "utc_now", lambda: NOW.replace(hour=20))
    # Use a controlled market snapshot, not real external services.
    monkeypatch.setattr(runner, "collect", lambda symbol, diagnostic=False: {
        "symbol": symbol, "m5_closed_utc": NOW.isoformat(), "candles": {},
        "h1_indicators": {}, "digits": 5, "bid": 1.1, "ask": 1.10008,
        "snapshot_age_seconds": 1800, "reference_price": 1.1,
    })
    fake = Mock(return_value=('{"action":"WAIT","reason":"Diagnóstico","sl":null,"tp":null}', (500, 40)))
    monkeypatch.setattr(runner, "call_provider", fake)
    args = SimpleNamespace(allow_api_cost=True, demo=False, loop=False, symbols=[SYMBOL],
                           providers=["gemini"], gemini_model="gemini-3.1-flash-lite",
                           openai_model="gpt-4.1-mini", max_call_usd=.05)
    runner.run_diagnostic(journal, args)
    runner.run_diagnostic(journal, args)
    assert fake.call_count == 1
    assert journal.execute("SELECT status FROM diagnostic_calls").fetchone()[0] == "DIAGNOSTIC_ONLY"
    assert journal.execute("SELECT COUNT(*) FROM prospective_cycles").fetchone()[0] == 0
    assert journal.execute("SELECT COUNT(*) FROM prospective_decisions").fetchone()[0] == 0
    assert store.budget(journal)["gemini"]["spent"] > 0
    mt5.order_send.assert_not_called()

def test_diagnostic_requires_explicit_cost_consent(journal):
    args = SimpleNamespace(allow_api_cost=False)
    with pytest.raises(ValueError, match="allow-api-cost"):
        runner.run_diagnostic(journal, args)


def test_cumulative_budget_includes_diagnostic_reservations(journal):
    with journal:
        journal.execute("""INSERT INTO diagnostic_calls
            (diagnostic_id,provider,symbol,model,started_utc,reserved_usd,status)
            VALUES ('legacy','gemini',?,?,?,2.49,'reserved')""", (SYMBOL, 'mock', NOW.isoformat()))
    later = NOW + timedelta(days=3)
    assert store.claim(journal, "two", "gemini", later, .02) == "presupuesto acumulado insuficiente"
    assert store.claim(journal, "two", "openai", later, .02) == "reserved"
    assert store.budget(journal)["gemini"]["remaining"] == pytest.approx(.01)
    assert store.budget(journal, later.date().isoformat())["gemini"]["attempts"] == 0


def test_openai_disabled_before_call(journal, mt5, monkeypatch):
    monkeypatch.setenv("OPENAI_ENABLED", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    call = Mock()
    monkeypatch.setattr(runner, "call_provider", call)
    result = runner.run_cycle(journal, SYMBOL, ["openai"], {"openai": "gpt-5.4-mini"}, .05)
    assert "desactivado" in result[0]
    call.assert_not_called()


def test_authenticated_entry_control_and_missing_mt5(journal, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("PROSPECTIVE_DB", journal.execute("PRAGMA database_list").fetchone()["file"])
    monkeypatch.setenv("LAB_CONTROL_TOKEN", "only-a-long-local-fixture-token")
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    with TestClient(app) as http:
        assert http.get("/api/dashboard").json()["current_balance"] is None
        result = http.get("/api/market/candles", params={"symbol": SYMBOL})
        assert result.status_code == 503
        assert result.json()["detail"]["code"] == "MT5_MODULE_UNAVAILABLE"
        denied = http.post("/api/controls/entries", json={"blocked": True})
        assert denied.status_code == 401
        allowed = http.post("/api/controls/entries", json={"blocked": True},
                            headers={"Authorization": "Bearer only-a-long-local-fixture-token"})
        assert allowed.status_code == 200 and store.entries_blocked(journal)
        assert http.get("/api/prospective/export?format=csv").text.startswith("cycle_id,symbol,")


def position_for_management():
    return SimpleNamespace(ticket=42, identifier=75, magic=demo.MAGIC, volume=.7,
                           price_open=1.10008, sl=1.0998, tp=1.101, type=0,
                           symbol=SYMBOL, time=int(NOW.timestamp()), profit=0, swap=0)


def test_modify_refuses_more_risk_and_manages_only_owned(journal, mt5, tmp_path):
    engine = executor(mt5, tmp_path)
    own = position_for_management()
    mt5.positions_get.return_value = (own,)
    engine.manage(journal, "lower_stop", SYMBOL, 75, "MODIFY", 1.099, 1.102, NOW.isoformat())
    engine.manage(journal, "not_ours", SYMBOL, 999, "CLOSE", None, None, NOW.isoformat())
    mt5.order_send.assert_not_called()

    def modify(request):
        assert request["action"] == mt5.TRADE_ACTION_SLTP
        own.sl, own.tp = request["sl"], request["tp"]
        return SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE)
    mt5.order_send.side_effect = modify
    engine.manage(journal, "move", SYMBOL, 75, "MODIFY", 1.09985, 1.102, NOW.isoformat())
    engine.manage(journal, "move", SYMBOL, 75, "MODIFY", 1.09985, 1.102, NOW.isoformat())
    assert mt5.order_send.call_count == 1
    assert journal.execute("SELECT status FROM demo_management WHERE cycle_id='move'").fetchone()[0] == "confirmed"


def test_uncertain_close_is_not_resent(journal, mt5, tmp_path):
    engine = executor(mt5, tmp_path)
    own = position_for_management()
    mt5.positions_get.return_value = (own,)
    mt5.order_send.return_value = None
    engine.manage(journal, "close_attempt", SYMBOL, 75, "CLOSE", None, None, NOW.isoformat())
    engine.manage(journal, "second_candle", SYMBOL, 75, "CLOSE", None, None, NOW.isoformat())
    assert mt5.order_send.call_count == 1
    assert journal.execute("SELECT status FROM demo_management").fetchone()[0] == "unconfirmed"
    mt5.positions_get.return_value = ()
    assert not engine.maintain(journal)
    assert journal.execute("SELECT status FROM demo_management").fetchone()[0] == "resolved"


def test_calendar_unverified_result_blocks_entries(journal, mt5, tmp_path):
    engine = executor(mt5, tmp_path)
    value = json.loads(engine.calendar.read_text())
    value["coverage_verified"] = False
    engine.calendar.write_text(json.dumps(value))
    engine.enter(journal, "no_calendar", SYMBOL, "BUY", 1.0998, 1.102, NOW.isoformat())
    mt5.order_send.assert_not_called()
    assert "sin cobertura verificada" in journal.execute("SELECT detail FROM prospective_demo_events").fetchone()[0]


def test_no_demo_start_with_unverified_commission(mt5, monkeypatch, tmp_path):
    config = tmp_path / "demo.json"
    config.write_text(json.dumps({SYMBOL:{"commission_usd_per_lot_roundtrip":0,"max_spread_points":12,
                                         "slippage_buffer_points_per_side":2,"commission_verified":False}}))
    monkeypatch.setenv("MT5_EXECUTION_CONFIG", str(config))
    monkeypatch.setenv("MT5_NEWS_CALENDAR", str(tmp_path/"news.json"))
    monkeypatch.setenv("MT5_DEMO_LOGIN","123")
    with pytest.raises(ValueError,match="MT5_EXECUTION_CONFIG"):
        demo.DemoExecutor.from_env("gemini", [SYMBOL])
    mt5.order_send.assert_not_called()


def test_historical_gemini_uses_same_budget(journal, monkeypatch):
    from app.legacy_meter import generate_content

    monkeypatch.setenv("PROSPECTIVE_DB", journal.execute("PRAGMA database_list").fetchone()["file"])
    monkeypatch.setenv("LAB_LEGACY_API_COST", "0")
    client = Mock()
    with pytest.raises(RuntimeError,match="LAB_LEGACY_API_COST"):
        generate_content(client, model="gemini-3.1-flash-lite", contents="fixture")
    assert store.claim(journal, "prior", "gemini", NOW, 2.49) == "reserved"
    with pytest.raises(RuntimeError,match="Presupuesto acumulado"):
        generate_content(client, model="gemini-3.1-flash-lite", contents="fixture", authorized=True)
    assert generate_content(client, model="gemini-3.1-flash-lite", contents="fixture",
                            authorized=True, ceiling=.01) is client.models.generate_content.return_value
    assert store.budget(journal)["gemini"]["remaining"] == pytest.approx(0)
