import sys,types,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
mt5=types.ModuleType('MetaTrader5');mt5.TIMEFRAME_M5=5;mt5.TIMEFRAME_M15=15;mt5.TIMEFRAME_H1=60
sys.modules.setdefault('MetaTrader5',mt5)
from app.historical_v17 import connect
from app.diagnostics_v181 import audit
class DiagnosticsTests(unittest.TestCase):
 def test_missing_costs_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   with connect(Path(tmp)/'hist.db') as db:
    with self.assertRaises(ValueError): audit(db)
 def test_no_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   with connect(Path(tmp)/'hist.db') as db:
    self.assertEqual(audit(db,spread_points=9,point_size=.00001)['status'],'insufficient_data')
 def test_invalid_limit(self):
  with tempfile.TemporaryDirectory() as tmp:
   with connect(Path(tmp)/'hist.db') as db:
    with self.assertRaises(ValueError):audit(db,spread_points=9,point_size=.00001,limit=0)
if __name__=='__main__':unittest.main()
