import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'backend' / 'primera_decision_gemini.py'
spec = importlib.util.spec_from_file_location('first_gemini', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class GeminiTests(unittest.TestCase):
    def test_temporal_boundary_and_session(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'history.sqlite3'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE historical_candles (symbol TEXT,timeframe TEXT,candle_time INTEGER,open REAL,high REAL,low REAL,close REAL,tick_volume INTEGER)')
            # 2026-11-17 14:00 UTC = 08:00 Managua.
            ts = 1794924000
            for tf, step in m.STEPS.items():
                for i in range(80):
                    t = ts - (80-i)*step
                    db.execute('INSERT INTO historical_candles VALUES (?,?,?,?,?,?,?,?)', ('EURUSD',tf,t,1.1,1.2,1.0,1.15,10))
            db.commit(); db.close()
            result = m.read_context(path, ts)
            for tf, candles in result['candles'].items():
                self.assertTrue(all(x['candle_time']+m.STEPS[tf] <= ts for x in candles))
            with self.assertRaises(ValueError):
                m.read_context(path, ts + 60)
    def test_response_validation(self):
        self.assertEqual(m.validate_answer({'decision':'WAIT','confidence':0.5,'reason':'No hay confirmación','stop_loss':None,'take_profit':None}, 1.1)[0], 'WAIT')
        with self.assertRaises(ValueError):
            m.validate_answer({'decision':'BUY','confidence':0.9,'reason':'Señal potencial','stop_loss':1.2,'take_profit':1.3}, 1.1)

if __name__ == '__main__': unittest.main()
