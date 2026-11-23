import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import demo_execution as exe
from app import news_calendar_sync as news

class FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    def order_calc_profit(self, direction, symbol, volume, entry, stop):
        return (stop-entry if direction == 0 else entry-stop) * 1000 * volume

class Tests(unittest.TestCase):
    def test_buy_and_sell_adverse_buffer(self):
        mt5 = FakeMT5()
        buy = exe.protected_loss(mt5, 0, 'EURUSDmicro', .1, 1.1, 1.099, .00001, 3, 0)
        sell = exe.protected_loss(mt5, 1, 'EURUSDmicro', .1, 1.1, 1.101, .00001, 3, 0)
        self.assertAlmostEqual(buy, .106, places=6)
        self.assertAlmostEqual(sell, .106, places=6)
    def test_commission_is_counted(self):
        mt5 = FakeMT5()
        self.assertAlmostEqual(exe.protected_loss(mt5, 0, 'x', .1, 1.1, 1.099, .00001, 3, .2), .126)
    def test_oversized_minimum_is_rejected_by_cap(self):
        mt5 = FakeMT5()
        risk = exe.protected_loss(mt5, 0, 'x', .1, 1.1, 1.097, .00001, 3, 0)
        self.assertGreater(risk, .25)
    def test_calendar_blocks_expired_and_high_impact(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'calendar.json'
            now = datetime(2026, 11, 23, 13, tzinfo=timezone.utc)
            payload = {'coverage_start_utc': '2026-11-23T12:00:00+00:00',
                       'coverage_end_utc': '2026-11-23T15:00:00+00:00',
                       'retrieved_utc': '2026-11-23T12:59:00+00:00', 'coverage_verified': True, 'currencies': ['EUR','USD'], 'source': 'fixture', 'events': [{'at_utc': '2026-11-23T13:05:00+00:00', 'currency': 'USD', 'impact': 'high', 'title': 'Test'}]}
            path.write_text(json.dumps(payload), encoding='utf-8')
            self.assertIn('alto impacto', exe.calendar_status(path, {'EUR','USD'}, now))
            self.assertIn('sin cobertura', exe.calendar_status(path, {'EUR','USD'}, datetime(2026,11,24,tzinfo=timezone.utc)))
    def test_news_rejects_naive_time(self):
        with self.assertRaises(ValueError):
            news.normalize_finnhub({'economicCalendar': [{'country':'US','impact':3,'time':'2026-11-23 13:30:00','event':'CPI'}]},
                                   datetime(2026,11,23,tzinfo=timezone.utc), datetime(2026,11,25,tzinfo=timezone.utc))
    def test_no_events_does_not_replace_existing_file(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,*args): return b'{"economicCalendar": []}'
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'calendar.json'; p.write_text('original')
            with self.assertRaises(ValueError):
                news.sync('test-key', p, opener=lambda *a,**kw: Reply())
            self.assertEqual(p.read_text(), 'original')

if __name__ == '__main__': unittest.main()
