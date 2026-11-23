"""V1.8: backtest exploratorio de solo lectura; NO envía órdenes a MT5.

Señal ejemplo: ruptura del máximo/mínimo de las 20 velas M5 cerradas
previas, filtro EMA20/EMA50 H1 cerradas, entrada en apertura de la
siguiente M5. SL=1 ATR14, TP=1.5 ATR14, salida máximo 12 M5.
Estrategia de demostración, NO validada ni optimizada.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from math import isclose
from .mt5_market import SYMBOLS


def _load(db,symbol,tf):
    return [dict(r) for r in db.execute('SELECT candle_time,open,high,low,close,tick_volume,spread_points FROM historical_candles WHERE symbol=? AND timeframe=? ORDER BY candle_time',(symbol,tf))]


def ohlc_report(db,symbol,limit=30,abs_tol=1e-8):
    if symbol not in SYMBOLS: raise ValueError('Símbolo no permitido')
    if not 1<=limit<=500: raise ValueError('limit fuera de rango')
    m5={r['candle_time']:r for r in _load(db,symbol,'M5')}
    result={}
    for tf,n in (('M15',3),('H1',12)):
        count=Counter(); anomalies=[]
        for higher in _load(db,symbol,tf):
            t=higher['candle_time']; window=[m5.get(t+300*i) for i in range(n)]
            if any(r is None for r in window):
                count['incomplete']+=1;continue
            aggregate={'open':window[0]['open'],'high':max(x['high'] for x in window),'low':min(x['low'] for x in window),'close':window[-1]['close']}
            wrong=[key for key,value in aggregate.items() if not isclose(value,higher[key],rel_tol=0,abs_tol=abs_tol)]
            if wrong:
                count['mismatch']+=1
                if len(anomalies)<limit:anomalies.append({'time':t,'utc':datetime.fromtimestamp(t,timezone.utc).isoformat(),'fields':wrong,'m5_aggregated':aggregate,'higher_recorded':{k:higher[k] for k in aggregate}})
            else:count['matched']+=1
        result[tf]={'matched':count['matched'],'mismatch':count['mismatch'],'incomplete':count['incomplete'],'mismatch_preview':anomalies}
    return {'symbol':symbol,'comparison':result,'note':'OHLC M5 agregado vs M15/H1 en ventanas completas. Las ventanas incompletas no se validan; sin interpolación.'}


def ema(values,period):
    """EMA definida desde el primer valor disponible; sólo datos anteriores/cerrados."""
    if not values:return []
    alpha=2/(period+1);out=[values[0]]
    for v in values[1:]:out.append(alpha*v+(1-alpha)*out[-1])
    return out


def atr(rows,period=14):
    if not rows:return []
    tr=[rows[0]['high']-rows[0]['low']]
    for a,b in zip(rows,rows[1:]):tr.append(max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close'])))
    return [None if i<period-1 else sum(tr[i-period+1:i+1])/period for i in range(len(rows))]


def backtest(db,symbol='EURUSD',train_fraction=.7,spread_points=None,slippage_points=0.,point_size=None,capital=100.,risk_pct=.25,max_bars=12):
    if symbol not in SYMBOLS:raise ValueError('Símbolo no permitido')
    if not .5<=train_fraction<=.85:raise ValueError('train_fraction entre 0.5 y 0.85')
    if spread_points is None or point_size is None:raise ValueError('spread_points y point_size explícitos obligatorios; no se inventan costos históricos')
    if not (0<=spread_points<=1000 and 0<=slippage_points<=1000 and 0<point_size<=1):raise ValueError('Costos o point_size inválidos')
    if not (0<risk_pct<=1 and capital>0 and 1<=max_bars<=48):raise ValueError('Parámetros de riesgo inválidos')
    m5=_load(db,symbol,'M5');h1=_load(db,symbol,'H1')
    if len(m5)<250 or len(h1)<70:return {'symbol':symbol,'status':'insufficient_data','m5':len(m5),'h1':len(h1)}
    # El filtro H1 de una señal M5 en t sólo puede usar H1 cerradas <= t+300.
    h20=ema([r['close'] for r in h1],20);h50=ema([r['close'] for r in h1],50)
    volatility=atr(m5);split=int(len(m5)*train_fraction);trades=[];rejected=Counter();hidx=-1;next_eligible=0
    for i in range(60,len(m5)-max_bars-1):
        if i<next_eligible:continue
        bar=m5[i];t=bar['candle_time'];signal_close=t+300
        while hidx+1<len(h1) and h1[hidx+1]['candle_time']+3600<=signal_close:hidx+=1
        if hidx<60:continue
        # Exige continuidad M5 en ventana de señal y entrada; evita cruzar cierres.
        if any(m5[j+1]['candle_time']-m5[j]['candle_time']!=300 for j in range(i-20,i+1)):
            rejected['non_contiguous_signal']+=1;continue
        if volatility[i] is None or volatility[i]<=0:continue
        prior=m5[i-20:i]
        direction=1 if bar['close']>max(x['high'] for x in prior) and h20[hidx]>h50[hidx] else (-1 if bar['close']<min(x['low'] for x in prior) and h20[hidx]<h50[hidx] else 0)
        if not direction:continue
        entry_index=i+1;entry=m5[entry_index]['open'];distance=volatility[i]
        if distance<=0:continue
        # No hay especificaciones MT5 de contrato/volumen mínimo en histórico: resultados por unidad nocional, NO P/L ejecutable.
        # Costos: spread completo y slippage de entrada/salida, en puntos de precio.
        cost=(spread_points+2*slippage_points)*point_size
        stop=entry-direction*distance;target=entry+direction*1.5*distance
        exit_price=None;exit_i=None;why=None
        for j in range(entry_index,entry_index+max_bars):
            r=m5[j]
            if j>entry_index and r['candle_time']-m5[j-1]['candle_time']!=300:
                why='session_gap';exit_i=None;break
            stop_hit=r['low']<=stop if direction==1 else r['high']>=stop
            target_hit=r['high']>=target if direction==1 else r['low']<=target
            if stop_hit and target_hit:exit_price=stop;why='both_hit_conservative_stop';exit_i=j;break
            if stop_hit:exit_price=stop;why='stop';exit_i=j;break
            if target_hit:exit_price=target;why='target';exit_i=j;break
        if why=='session_gap':rejected['gap_during_trade']+=1;next_eligible=j+1;continue
        if exit_i is None:exit_i=entry_index+max_bars-1;exit_price=m5[exit_i]['close'];why='time_exit'
        gross=direction*(exit_price-entry)/entry
        net=(direction*(exit_price-entry)-cost)/entry
        # Evitar que un trade cruce la frontera train/test, incluso en salida.
        if i<split<=exit_i:rejected['cross_split']+=1;next_eligible=exit_i+1;continue
        trades.append({'signal_time':t,'entry_time':m5[entry_index]['candle_time'],'exit_time':m5[exit_i]['candle_time'],'side':'BUY' if direction==1 else 'SELL','entry':entry,'exit':exit_price,'stop':stop,'target':target,'exit_reason':why,'gross_fraction':gross,'net_fraction':net,'split':'train' if i<split else 'test'})
        next_eligible=exit_i+1
    def metrics(group):
        if not group:return {'count':0,'mean_net_fraction':None,'win_rate':None,'max_drawdown_fraction':None,'profit_factor':None}
        # Capital nominal fijo por operación (no volumen de lote); no es P/L de MT5.
        returns=[t['net_fraction'] for t in group];wealth=1.;peak=1.;maxdd=0.
        for r in returns:wealth*=max(0.,1+r);peak=max(peak,wealth);maxdd=max(maxdd,1-wealth/peak)
        gains=sum(max(0.,x) for x in returns);losses=-sum(min(0.,x) for x in returns)
        return {'count':len(returns),'mean_net_fraction':sum(returns)/len(returns),'win_rate':sum(x>0 for x in returns)/len(returns),'max_drawdown_fraction':maxdd,'profit_factor':gains/losses if losses else None}
    return {'symbol':symbol,'status':'exploratory_only','strategy':'breakout20_H1_EMA20_50_ATR14_SL1_TP1.5_max12M5','train_fraction':train_fraction,'split_time':m5[split]['candle_time'],'cost_assumptions':{'spread_points':spread_points,'slippage_points_per_side':slippage_points,'point_size':point_size},'risk_policy':{'virtual_capital_usd':capital,'risk_per_trade_pct':risk_pct,'execution_feasibility':'NOT_VERIFIED: MT5 min lot, contract size, tick value and stops must be checked before simulation of dollars'},'train':metrics([t for t in trades if t['split']=='train']),'test':metrics([t for t in trades if t['split']=='test']),'rejected':dict(rejected),'trades_preview':trades[:25],'trade_count':len(trades),'warnings':['Estrategia demostrativa no optimizada; no inferir ventaja estadística.','No incluye comisiones, swaps, spreads históricos, fills, gaps de precio ni volumen mínimo MT5.','Si la vela toca SL y TP se presupone SL primero; no se utilizan velas posteriores para decidir la entrada.']}
