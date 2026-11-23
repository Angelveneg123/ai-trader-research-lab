import importlib.util
import sqlite3
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'backend' / 'app' / 'audit_v16.py'
spec = importlib.util.spec_from_file_location('audit_v16', MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

def candles(n, step, base=1.10):
    return [{'time':i*step,'open':base,'high':max(base+.002,base+.0001*i),'low':base-.002,'close':base+.0001*i,'volume':10} for i in range(n)]

def test_temporal_guard():
    m5=candles(300,300)
    cutoff=m5[-1]['time']+300
    h1=[c for c in candles(30,3600) if c['time']+3600<=cutoff]
    m15=[c for c in candles(100,900) if c['time']+900<=cutoff]
    d,r,ctx=audit.build('EURUSD',m5,m15,h1)
    assert ctx['temporal_validation']=='PASS'
    assert ctx['h1']['ema20'] is not None
    try:
        audit.build('EURUSD',m5,m15+[{'time':cutoff,'open':1,'high':2,'low':.5,'close':1,'volume':1}],h1)
    except ValueError as e:
        assert 'LOOKAHEAD' in str(e)
    else:
        raise AssertionError('No rechazó información futura')

def test_outcomes_only_closed():
    with sqlite3.connect(':memory:') as db:
        db.row_factory=sqlite3.Row
        audit.init(db)
        context={'candle_time':0,'m5':{'close':1.1},'spread_snapshot':None}
        assert audit.insert(db,'EURUSD','ESPERAR','test',context)
        assert not audit.insert(db,'EURUSD','ESPERAR','test',context)
        assert audit.update_outcomes(db,'EURUSD',candles(3,300))==0
        assert audit.update_outcomes(db,'EURUSD',candles(4,300))==1
        assert audit.update_outcomes(db,'EURUSD',candles(4,300))==0
        assert audit.list_audit(db)[0]['outcomes'][0]['horizon']==3

def test_rejects_misaligned_candle():
    m5=candles(300,300)
    cutoff=m5[-1]['time']+300
    h1=[c for c in candles(30,3600) if c['time']+3600<=cutoff]
    m15=[c for c in candles(100,900) if c['time']+900<=cutoff]
    m15[0]['time']+=1
    import pytest
    with pytest.raises(ValueError, match='Alineación temporal'):
        audit.build('EURUSD',m5,m15,h1)

def test_outcomes_reject_gaps_and_do_not_use_late_spread():
    with sqlite3.connect(':memory:') as db:
        db.row_factory=sqlite3.Row
        audit.init(db)
        context={'candle_time':0,'m5':{'close':1.1},'spread_snapshot':{'bid':1.1,'ask':1.101,'sampled_at':400}}
        audit.insert(db,'EURUSD','ESPERAR','test',context)
        series=candles(4,300)
        assert audit.update_outcomes(db,'EURUSD',[series[0],series[1],series[3]])==0
        assert audit.update_outcomes(db,'EURUSD',series)==1
        outcome=audit.list_audit(db)[0]['outcomes'][0]
        assert outcome['net_return_estimate'] is None
        assert outcome['spread_cost_estimate'] is None
