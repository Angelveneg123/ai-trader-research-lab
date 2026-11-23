import sys,types,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
mt5=types.ModuleType('MetaTrader5');mt5.TIMEFRAME_M5=5;mt5.TIMEFRAME_M15=15;mt5.TIMEFRAME_H1=60
sys.modules.setdefault('MetaTrader5',mt5)
from app.historical_v17 import connect
from app.backtest_v18 import ohlc_report,backtest
class BacktestTests(unittest.TestCase):
 def test_ohlc_match_and_mismatch(self):
  with tempfile.TemporaryDirectory() as tmp:
   with connect(Path(tmp)/'hist.db') as db:
    for i,(o,h,l,c) in enumerate([(1,1.2,.9,1.1),(1.1,1.3,1,1.2),(1.2,1.4,1.1,1.3)]):
     db.execute('INSERT INTO historical_candles(symbol,timeframe,candle_time,open,high,low,close,tick_volume,imported_at) VALUES (?,?,?,?,?,?,?,?,?)',('EURUSD','M5',i*300,o,h,l,c,1,'now'))
    db.execute('INSERT INTO historical_candles(symbol,timeframe,candle_time,open,high,low,close,tick_volume,imported_at) VALUES (?,?,?,?,?,?,?,?,?)',('EURUSD','M15',0,1,1.4,.9,1.3,3,'now'))
    self.assertEqual(ohlc_report(db,'EURUSD')['comparison']['M15']['matched'],1)
    db.execute('UPDATE historical_candles SET high=1.5 WHERE symbol="EURUSD" AND timeframe="M15"')
    self.assertEqual(ohlc_report(db,'EURUSD')['comparison']['M15']['mismatch'],1)
 def test_explicit_costs_required(self):
  with tempfile.TemporaryDirectory() as tmp:
   with connect(Path(tmp)/'hist.db') as db:
    with self.assertRaises(ValueError):backtest(db,'EURUSD')
    self.assertEqual(backtest(db,'EURUSD',spread_points=10,point_size=.00001)['status'],'insufficient_data')
 def test_read_only(self):
  with tempfile.TemporaryDirectory() as tmp:
   with connect(Path(tmp)/'hist.db') as db:
    before=db.execute('SELECT count(*) FROM historical_candles').fetchone()[0]
    ohlc_report(db,'EURUSD');backtest(db,'EURUSD',spread_points=10,point_size=.00001)
    self.assertEqual(db.execute('SELECT count(*) FROM historical_candles').fetchone()[0],before)
if __name__=='__main__':unittest.main()
