import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
# MetaTrader5 is Windows-only: test validation and persistence with a stub.
import types
mt5=types.ModuleType('MetaTrader5')
mt5.TIMEFRAME_M5=5; mt5.TIMEFRAME_M15=15; mt5.TIMEFRAME_H1=60
mt5.ACCOUNT_TRADE_MODE_DEMO=0
sys.modules.setdefault('MetaTrader5',mt5)
from app import historical_v17 as hist

class Rate(dict):
    @property
    def dtype(self):
        return types.SimpleNamespace(names=tuple(self))

class FakeMT5:
    TIMEFRAME_M5=5; TIMEFRAME_M15=15; TIMEFRAME_H1=60
    ACCOUNT_TRADE_MODE_DEMO=0
    def initialize(self): return True
    def account_info(self): return types.SimpleNamespace(trade_mode=0)
    def symbol_select(self,*args): return True
    def shutdown(self): pass
    def copy_rates_range(self,symbol,tf,start,end):
        # 2026-08-03 00:00 UTC, only two contiguous M5 bars
        t=1785715200
        return [Rate(time=x,open=1.0,high=1.2,low=.9,close=1.1,tick_volume=10,spread=2,real_volume=0)
                for x in (t,t+300) if start.timestamp()<=x<=end.timestamp()]

class HistoryTests(unittest.TestCase):
    def test_validation_rejects_future_or_bad_ohlc(self):
        r=Rate(time=1785715200,open=1,high=1.2,low=.9,close=1.1,tick_volume=10,spread=2,real_volume=0)
        self.assertIsNotNone(hist.validate_rate(r,300,1785715200,1785716100,1785716100))
        self.assertIsNone(hist.validate_rate(r,300,1785715200,1785716100,1785715400))
        r['high']=.5
        self.assertIsNone(hist.validate_rate(r,300,1785715200,1785716100,1785716100))
    def test_import_is_idempotent_and_separate(self):
        with tempfile.TemporaryDirectory() as d:
            dbpath=Path(d)/'historical.sqlite3'
            with hist.connect(dbpath) as db:
                start=datetime(2026,8,3,tzinfo=timezone.utc)
                end=datetime(2026,8,4,tzinfo=timezone.utc)
                with patch.object(hist,'datetime',wraps=datetime) as mocked:
                    mocked.now.return_value=datetime(2026,11,19,tzinfo=timezone.utc)
                    a=hist.import_history(db,FakeMT5(),start,end,symbols=('EURUSD',),timeframes=('M5',))
                    b=hist.import_history(db,FakeMT5(),start,end,symbols=('EURUSD',),timeframes=('M5',))
                self.assertEqual(a['inserted'],2)
                self.assertEqual(b['inserted'],0)
                self.assertEqual(b['duplicates'],2)
                self.assertEqual(hist.quality(db,'EURUSD','M5')['candles'],2)
                self.assertNotIn('observations',[r[0] for r in db.execute('SELECT name FROM sqlite_master')])

if __name__=='__main__':unittest.main()
