from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .mt5_market import get_candles, get_mt5_status, get_quote_snapshot
from .mt5_connection import MT5Unavailable
from .operations_api import router as operations_router, authenticate
from .ai_dashboard import snapshot
from .market_symbols import MICRO_SYMBOLS, live_symbols, load_settings, valid_market_symbol
from .prospective_store import latest_market_cycles, snapshot as prospective_snapshot
from .research import get_observations, get_status, start_worker, get_audit, get_metrics

@asynccontextmanager
async def lifespan(app):
    stop, thread = start_worker()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=10)

app = FastAPI(title='AI Trader Research Lab', version='2.5', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'], allow_methods=['GET','POST'], allow_headers=['*'])

app.include_router(operations_router)

class Settings(BaseModel):
    initial_balance: float = 100.0
    risk_per_trade_pct: float = 0.25
    daily_loss_limit_pct: float = 1.0
    openai_budget: float = 2.5
    gemini_budget: float = 2.5
    symbols: list[str] = ['XAUUSD', 'EURUSD', 'USDJPY']
    execution_mode: str = 'dry-run'

SETTINGS = Settings()

@app.get('/api/health')
def health():
    s = get_mt5_status()
    prospect = prospective_snapshot()
    return {'status': 'ok', 'version': app.version, 'mt5_connected': s['connected'],
            'mt5_error_code': s['error_code'], 'runtime': prospect['runtime']}


@app.get('/api/dashboard')
def dashboard():
    now = datetime.now(ZoneInfo('America/Managua'))
    s = get_mt5_status()
    p = prospective_snapshot(limit=1)
    demo, metrics = p['demo'], p['metrics']
    same_day = demo and demo['local_day'] == now.date().isoformat()
    open_session = now.weekday() < 5 and 2 <= now.hour < 10
    return {
        'version': app.version, 'as_of': now.isoformat(), 'initial_balance': SETTINGS.initial_balance,
        'current_balance': s['balance'], 'equity': s['equity'],
        'realized_pnl': demo['realized_usd'] if same_day and s['connected'] else None,
        'floating_pnl': demo['floating_usd'] if same_day and s['connected'] else None,
        'daily_drawdown_usd': metrics['daily_drawdown_usd'] if same_day and metrics and s['connected'] else None,
        'open_positions': metrics['positions'] if same_day and metrics and s['connected'] else None,
        'trades': p['demo_deals'], 'decisions': p['recent'], 'ai_research': snapshot(),
        'session_allows_entries': open_session, 'entries_blocked': p['entries_blocked'],
        'execution_mode': p['runtime']['mode'] if p['runtime'] else 'idle',
        'api_budgets': p['budget'], 'runtime': p['runtime'],
        'symbols': list(dict.fromkeys((*live_symbols(), *SETTINGS.symbols))),
        'data_source': 'deriv_mt5' if s['connected'] else 'not_connected',
        'mt5_connected': s['connected'], 'mt5_terminal_trade_allowed': s['terminal_trade_allowed'],
        'mt5_account_trade_allowed': s['account_trade_allowed'], 'mt5_demo': s['demo'],
        'mt5_balance': s['balance'], 'mt5_error': s['error'], 'mt5_error_code': s['error_code'],
        'mt5_native_code': s['mt5_code'], 'mt5_server': s['server'],
        'research': get_status(),
    }

@app.get('/api/config')
def config():
    return SETTINGS.model_dump()

@app.get('/api/market/status')
def market_status():
    return get_mt5_status()

@app.get('/api/market/candles')
def market_candles(symbol: str = 'EURUSD', timeframe: str = 'M5', limit: int = Query(200, ge=1, le=1000),
                   include_quote: bool = False):
    try:
        return get_candles(symbol, timeframe, limit, include_quote=include_quote)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except MT5Unavailable as exc:
        raise HTTPException(503, {"code": exc.code, "message": str(exc), "mt5_code": exc.native_code})
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.get('/api/market/quote')
def market_quote(symbol: str = 'EURUSDmicro'):
    if not valid_market_symbol(symbol):
        raise HTTPException(400, "Símbolo no permitido")
    quote = get_quote_snapshot(symbol)
    if quote is None:
        raise HTTPException(503, "Cotización de MT5 no disponible")
    return quote


@app.get('/api/research/status')
def research_status():
    return get_status()

@app.get('/api/research/observations')
def research_observations(symbol: str | None = None, limit: int = Query(50, ge=1, le=200)):
    try:
        return {'observations': get_observations(symbol, limit)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get('/api/research/audit')
def research_audit(symbol: str | None = None, limit: int = Query(50, ge=1, le=200)):
    try:
        return {'audits': get_audit(symbol,limit)}
    except ValueError as exc:
        raise HTTPException(400,str(exc))

@app.get('/api/research/metrics')
def research_metrics():
    return get_metrics()


@app.get('/api/history/status')
def historical_status():
    from .historical_v17 import connect, status
    with connect() as db:
        return status(db)

@app.get('/api/history/quality')
def historical_quality(symbol: str = 'EURUSD', timeframe: str = 'M5'):
    from .historical_v17 import connect, quality
    from .mt5_market import SYMBOLS, TIMEFRAMES
    if symbol not in SYMBOLS or timeframe not in TIMEFRAMES:
        raise HTTPException(400, 'Símbolo o temporalidad no permitida')
    with connect() as db:
        return quality(db,symbol,timeframe)


@app.get('/api/history/gaps')
def historical_gaps(symbol: str = 'EURUSD', timeframe: str = 'M5', limit: int = Query(100,ge=1,le=1000)):
    from .historical_v17 import connect
    from .quality_v171 import gap_report
    try:
        with connect() as db: return gap_report(db,symbol,timeframe,limit)
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.get('/api/history/alignment')
def historical_alignment(symbol: str = 'EURUSD', limit: int = Query(50,ge=1,le=500)):
    from .historical_v17 import connect
    from .quality_v171 import alignment_report
    try:
        with connect() as db: return alignment_report(db,symbol,limit)
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.get('/api/history/rejections')
def historical_rejections():
    from .historical_v17 import connect
    from .quality_v171 import rejected_report
    with connect() as db: return rejected_report(db)


@app.get('/api/backtest/ohlc')
def backtest_ohlc(symbol: str = 'EURUSD', limit: int = Query(30,ge=1,le=500)):
    from .historical_v17 import connect
    from .backtest_v18 import ohlc_report
    try:
        with connect() as db: return ohlc_report(db,symbol,limit)
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.get('/api/backtest/run')
def backtest_run(symbol: str = 'EURUSD', spread_points: float | None = Query(None,ge=0),
                 point_size: float | None = Query(None,gt=0), slippage_points: float = Query(0,ge=0),
                 train_fraction: float = Query(.7,ge=.5,le=.85)):
    from .historical_v17 import connect
    from .backtest_v18 import backtest
    try:
        with connect() as db: return backtest(db,symbol,train_fraction,spread_points,slippage_points,point_size)
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.get('/api/backtest/audit')
def backtest_audit(symbol: str = 'EURUSD', spread_points: float | None = Query(None,ge=0),
                   point_size: float | None = Query(None,gt=0), slippage_points: float = Query(0,ge=0),
                   train_fraction: float = Query(.7,ge=.5,le=.85),limit: int=Query(30,ge=1,le=200)):
    from .historical_v17 import connect
    from .diagnostics_v181 import audit
    try:
        with connect() as db: return audit(db,symbol,spread_points,point_size,slippage_points,train_fraction,limit)
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.get('/api/ai/status')
def ai_status(symbol: str = 'EURUSD'):
    if symbol not in SETTINGS.symbols:
        raise HTTPException(400, 'Símbolo no permitido')
    return snapshot(symbol)

# V1.9.6 research experiment; these routes never send MT5 orders.
from .gemini_protocol import status as gemini_protocol_status, prepare_manifest, start_batch

class BatchRequest(BaseModel):
    confirm: bool = False
    max_calls: int = 10
    usd_per_call_ceiling: float = 0.10
    max_estimated_usd: float = 1.00

@app.get('/api/gemini/protocol')
def protocol_status():
    try: return gemini_protocol_status()
    except ValueError as exc: raise HTTPException(409,str(exc))

@app.post('/api/gemini/protocol/prepare')
def protocol_prepare():
    try: return prepare_manifest()
    except ValueError as exc: raise HTTPException(409,str(exc))

@app.post('/api/gemini/protocol/run')
def protocol_run(req: BatchRequest, authorization: str | None = Header(default=None)):
    authenticate(authorization)
    if not req.confirm: raise HTTPException(400,'Confirmación explícita requerida')
    try: return start_batch(req.max_calls,req.usd_per_call_ceiling,req.max_estimated_usd)
    except ValueError as exc: raise HTTPException(409,str(exc))


@app.get('/api/prospective')
def prospective_status(symbol: str | None = None, limit: int = Query(30, ge=1, le=100)):
    if symbol is not None and not valid_market_symbol(symbol):
        raise HTTPException(400, 'Símbolo no permitido')
    load_settings()
    result = prospective_snapshot(symbol, limit)
    from .prospective_outcomes import news_snapshot
    return {**result, 'news': news_snapshot()}


@app.get('/api/prospective/markets')
def prospective_markets():
    labels = ('EUR/USD', 'USD/JPY', 'XAU/USD')
    configured = live_symbols()
    symbols = tuple(next((symbol for symbol in configured if symbol.upper().startswith(label.replace('/', ''))), default)
                    for label, default in zip(labels, MICRO_SYMBOLS))
    latest = latest_market_cycles(symbols)
    return {'markets': [{'label': label, 'symbol': symbol, 'latest': latest[symbol]}
                        for label, symbol in zip(labels, symbols)]}


DASHBOARD_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (DASHBOARD_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=DASHBOARD_DIST, html=True), name="dashboard")
