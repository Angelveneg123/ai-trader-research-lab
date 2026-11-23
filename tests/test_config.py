from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.main import SETTINGS

def test_safe_defaults():
    assert SETTINGS.execution_mode == 'dry-run'
    assert SETTINGS.initial_balance == 100
    assert SETTINGS.risk_per_trade_pct == 0.25
    assert SETTINGS.daily_loss_limit_pct == 1
    assert SETTINGS.openai_budget + SETTINGS.gemini_budget == 5
