"""V1.8.1: auditoría exploratoria de ejecuciones; solo lectura y sin órdenes."""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from .backtest_v18 import backtest, _load


def audit(db, symbol='EURUSD', spread_points=None, point_size=None, slippage_points=0., train_fraction=.7, limit=30):
    if not 1 <= limit <= 200:
        raise ValueError('limit fuera de rango')
    base=backtest(db,symbol,train_fraction,spread_points,slippage_points,point_size)
    if base.get('status')!='exploratory_only':
        return {'status':base['status'],'symbol':symbol}
    # El motor V1.8 no devuelve todas las operaciones: la vista previa no es una muestra aleatoria.
    preview=base['trades_preview']
    same_bar=[t for t in preview if t['entry_time']==t['exit_time']]
    by_reason=Counter(t['exit_reason'] for t in preview)
    by_side=Counter(t['side'] for t in preview)
    m5=_load(db,symbol,'M5')
    m5_by_time={r['candle_time']:r for r in m5}
    intrabar=[]
    for t in same_bar:
        bar=m5_by_time.get(t['entry_time'])
        if not bar:continue
        intrabar.append({'entry_time_utc':datetime.fromtimestamp(t['entry_time'],timezone.utc).isoformat(),
                         'side':t['side'],'exit_reason':t['exit_reason'],
                         'entry_at_bar_open':t['entry']==bar['open'],
                         'limitation':'OHLC M5 no determina el orden intrabar ni el fill efectivo'})
    # Escenarios independientes, no una optimización; no se selecciona el mejor.
    sensitivity=[]
    for spread_multiplier in (1.,1.5,2.):
        scenario_spread=spread_points*spread_multiplier
        res=base if spread_multiplier==1. else backtest(db,symbol,train_fraction,scenario_spread,slippage_points,point_size)
        sensitivity.append({'spread_points':scenario_spread,'slippage_points_per_side':slippage_points,
                            'train_profit_factor':res['train']['profit_factor'],
                            'test_profit_factor':res['test']['profit_factor'],
                            'test_mean_net_fraction':res['test']['mean_net_fraction'],
                            'test_count':res['test']['count']})
    return {'version':'1.8.1','symbol':symbol,'status':'AUDIT_ONLY_NOT_EXECUTABLE',
            'baseline':{'train':base['train'],'test':base['test'],'trade_count':base['trade_count'],
                        'rejected':base['rejected']},
            'preview_audit':{'preview_count':len(preview),'same_bar_exits':len(same_bar),
                             'exit_reasons':dict(by_reason),'sides':dict(by_side),
                             'same_bar_examples':intrabar[:limit],
                             'scope_warning':'Sólo se auditan las primeras 25 operaciones devueltas por V1.8, NO todas las operaciones'},
            'spread_sensitivity':sensitivity,
            'execution_checks':{
                'one_position_at_a_time':'Motor V1.8 usa next_eligible, pero falta auditoría independiente sobre el listado completo',
                'intrabar_order':'NO_VERIFICADO; el OHLC M5 no revela secuencia real de máximos y mínimos',
                'entry_price':'Apertura M5, sin simulación de fills ni bid/ask históricos',
                'slippage':'Constante supuesto; no basado en ejecuciones históricas',
                'lot_minimum':'NO_VERIFICADO',
                'tick_value_and_contract_size':'NO_VERIFICADO',
                'stops_level':'NO_VERIFICADO',
                'commission_and_swap':'NO_INCLUIDOS',
                'virtual_capital_usd':100.,'risk_per_trade_usd':.25,
                'pnl_usd':'NO_CALCULABLE con datos actuales'},
            'warnings':['No usar este informe como prueba de rentabilidad.',
                        'La sensibilidad al spread es una prueba de estrés, no una búsqueda de parámetros óptimos.',
                        'No usar resultados de prueba para elegir estrategia o parámetros.',
                        'No se modifica el histórico ni se envían órdenes.']}
