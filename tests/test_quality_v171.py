import sys,types,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
mt5=types.ModuleType('MetaTrader5')
mt5.TIMEFRAME_M5=5;mt5.TIMEFRAME_M15=15;mt5.TIMEFRAME_H1=60
sys.modules.setdefault('MetaTrader5',mt5)
from app.historical_v17 import connect
from app.quality_v171 import gap_report,alignment_report,rejected_report,classify_gap

class QualityTests(unittest.TestCase):
    def test_gap_and_alignment_without_interpolation(self):
        with tempfile.TemporaryDirectory() as d:
            with connect(Path(d)/'hist.db') as db:
                t=1785715200
                for tf,step,offsets in [('M5',300,[0,1,3]),('M15',900,[0]),('H1',3600,[0])]:
                    for i in offsets:
                        db.execute('''INSERT INTO historical_candles
                        (symbol,timeframe,candle_time,open,high,low,close,tick_volume,imported_at)
                        VALUES (?,?,?,?,?,?,?,?,?)''',('EURUSD',tf,t+step*i,1,1.1,.9,1,10,'now'))
                db.commit()
                self.assertEqual(gap_report(db,'EURUSD','M5')['missing_intervals'],1)
                a=alignment_report(db,'EURUSD')['alignment']
                self.assertEqual(a['M15']['incomplete_m5_windows'],1)
                self.assertEqual(a['H1']['incomplete_m5_windows'],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM historical_candles').fetchone()[0],5)
                self.assertFalse(rejected_report(db)['individual_rejection_reasons_available'])
    def test_classification(self):
        self.assertEqual(classify_gap('EURUSD','M5',1786135800,1786309800),'probable_weekend')
        self.assertEqual(classify_gap('EURUSD','M5',1787925600,1787926500),'requires_review')
if __name__=='__main__':unittest.main()
