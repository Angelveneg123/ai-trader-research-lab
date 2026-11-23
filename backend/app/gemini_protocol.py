"""Frozen historical research protocol; never interacts with MT5."""
import hashlib, json, os, random, sqlite3, threading, traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
HISTORY=ROOT/'data'/'historical.sqlite3'
JOURNAL=ROOT/'data'/'ai_decisions.sqlite3'
MANIFEST=ROOT/'data'/'gemini_v196_manifest.json'
TZ=ZoneInfo('America/Managua')
SEED=1962026
TARGET=89
_lock=threading.Lock()
_state={'running':False,'attempted':0,'last_error':None,'last_message':'Sin lotes ejecutados'}

def _read_existing():
    if not JOURNAL.exists(): return set(),0
    with sqlite3.connect(f'file:{JOURNAL.resolve().as_posix()}?mode=ro',uri=True) as db:
        rows=db.execute("SELECT decision_time_utc FROM ai_historical_decisions WHERE symbol='EURUSD'").fetchall()
    return {int(datetime.fromisoformat(r[0]).timestamp()) for r in rows},len(rows)

def _hash_context(context):
    raw=json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()

def _manifest_hash(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def prepare_manifest():
    if MANIFEST.exists(): return status()
    if not HISTORY.exists(): raise ValueError('No existe data/historical.sqlite3')
    from primera_decision_gemini import read_context,MODEL
    existing,_=_read_existing()
    with sqlite3.connect(f'file:{HISTORY.resolve().as_posix()}?mode=ro',uri=True) as db:
        timestamps=[r[0]+300 for r in db.execute("SELECT candle_time FROM historical_candles WHERE symbol='EURUSD' AND timeframe='M5' ORDER BY candle_time")]
    groups={}
    for ts in timestamps:
        loc=datetime.fromtimestamp(ts,TZ)
        if 2<=loc.hour<10 and loc.minute%15==0 and ts not in existing:
            groups.setdefault(loc.date().isoformat(),[]).append(ts)
    rng=random.Random(SEED)
    days=sorted(groups);rng.shuffle(days)
    selected=[];used_days=set()
    # One candidate per new day; avoids overlap with already examined pilot days.
    pilot_days={datetime.fromtimestamp(t,TZ).date().isoformat() for t in existing}
    # Prefer one scenario per day, then add a second at least five hours apart.
    for pass_number in (0,1):
        for day in days:
            if day in pilot_days:continue
            options=groups[day][:];rng.shuffle(options)
            existing_day=[int(datetime.fromisoformat(x['asof_utc']).timestamp()) for x in selected if x['local_time'][:10]==day]
            if len(existing_day)!=pass_number:continue
            for ts in options:
                if any(abs(ts-prev)<5*3600 for prev in existing_day):continue
                try:
                    ctx=read_context(HISTORY,ts)
                    if datetime.fromtimestamp(ts,TZ).hour==9 and datetime.fromtimestamp(ts,TZ).minute>=55:continue
                    selected.append({'asof_utc':ctx['decision_time_utc'],'context_sha256':_hash_context(ctx),'local_time':ctx['decision_time_managua']})
                    break
                except ValueError:continue
            if len(selected)==TARGET:break
        if len(selected)==TARGET:break
    if len(selected)<TARGET:raise ValueError(f'Hay {len(selected)} escenarios elegibles; se necesitan {TARGET}. No se creará manifiesto parcial.')
    document={'protocol':'V1.9.6-FROZEN-1','seed':SEED,'symbol':'EURUSD','model':MODEL,'session':'02:00-10:00 America/Managua','evaluation':'V1.9.2 M5 SESSION_CLOSE','target_new':TARGET,'selection':'prefer one per non-pilot day; optional second >=5h apart, UTC 15-min grid, shuffled seed; no future OHLC','scenarios':selected}
    document['manifest_sha256']=_manifest_hash(document)
    MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    with MANIFEST.open('x',encoding='utf-8') as f:json.dump(document,f,ensure_ascii=False,indent=2)
    return status()

def _load():
    if not MANIFEST.exists():return None
    doc=json.loads(MANIFEST.read_text(encoding='utf-8'))
    expected=doc.get('manifest_sha256');body={k:v for k,v in doc.items() if k!='manifest_sha256'}
    if expected!=_manifest_hash(body):raise ValueError('Manifiesto alterado: huella SHA256 inválida')
    return doc

def status():
    doc=_load()
    existing,total=_read_existing()
    completed=sum(int(datetime.fromisoformat(s['asof_utc']).timestamp()) in existing for s in doc['scenarios']) if doc else 0
    with _lock: state=dict(_state)
    return {'manifest_ready':doc is not None,'manifest_hash':doc['manifest_sha256'] if doc else None,
            'target_new':TARGET,'completed_new':completed,'pending_new':TARGET-completed,'historical_decisions_total':total,
            'model':doc['model'] if doc else None,'budget_verified_usd':None,'api_availability':'not_checked',**state,
            'orders_sent':False}

def _run_batch(max_calls,per_call_ceiling,max_estimated_usd):
    from dotenv import load_dotenv
    load_dotenv(ROOT/'backend'/'.env')
    try:
        from google import genai
        from google.genai import types
        from primera_decision_gemini import read_context,validate_answer,init_journal
        from evaluar_sesion_v192 import evaluate
        from lote_gemini_v193 import SCHEMA,fetch_future
        import uuid,time
        doc=_load();client=genai.Client(api_key=os.environ['GEMINI_API_KEY'],http_options=types.HttpOptions(timeout=30000))
        with sqlite3.connect(JOURNAL) as db,sqlite3.connect(f'file:{HISTORY.resolve().as_posix()}?mode=ro',uri=True) as hist:
            db.row_factory=sqlite3.Row;hist.row_factory=sqlite3.Row
            init_journal(db)
            db.execute('''CREATE TABLE IF NOT EXISTS ai_session_evaluations_v192 (
                decision_id TEXT PRIMARY KEY,evaluated_at_utc TEXT NOT NULL,outcome TEXT NOT NULL,bars_checked INTEGER NOT NULL,
                exit_time_utc TEXT,gross_pips_reference REAL,detail TEXT NOT NULL,method TEXT NOT NULL)''');db.commit()
            for item in doc['scenarios']:
                with _lock:
                    if _state['attempted']>=max_calls:break
                asof=item['asof_utc']
                if db.execute('SELECT 1 FROM ai_historical_decisions WHERE decision_time_utc=? AND symbol=? AND model=? AND context_sha256=?',(asof,'EURUSD',doc['model'],item['context_sha256'])).fetchone():continue
                context=read_context(HISTORY,int(datetime.fromisoformat(asof).timestamp()))
                if _hash_context(context)!=item['context_sha256']:raise ValueError('Histórico modificado: contexto no coincide con manifiesto')
                payload=json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                with _lock:
                    _state['attempted']+=1
                    _state['last_message']=f"Consultando {_state['attempted']} de {max_calls}: {asof}"
                from .legacy_meter import generate_content
                response=generate_content(client,model=doc['model'],ceiling=per_call_ceiling,authorized=True,contents=('Analizá SOLO estas velas cerradas históricas, sin datos futuros. Elegí BUY, SELL o WAIT. Ante incertidumbre WAIT. confidence numérica 0..1, nunca porcentaje 0..100. SL y TP respecto al último cierre M5, o null ambos si WAIT. No inventes noticias, spread, ejecución ni resultados. Justificá usando exclusivamente los datos. Contexto: '+payload),config=types.GenerateContentConfig(temperature=0,max_output_tokens=500,response_mime_type='application/json',response_schema=SCHEMA))
                answer=json.loads(response.text or '')
                action,conf,reason,sl,tp=validate_answer(answer,context['candles']['M5'][-1]['close'])
                did=uuid.uuid4().hex
                db.execute('''INSERT INTO ai_historical_decisions (decision_id,created_at_utc,decision_time_utc,symbol,model,context_sha256,context_json,decision,confidence,reason,stop_loss,take_profit,raw_response_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (did,datetime.now().astimezone().isoformat(),asof,'EURUSD',doc['model'],item['context_sha256'],payload,action,conf,reason,sl,tp,json.dumps(answer,ensure_ascii=False)))
                db.commit()
                decision=dict(db.execute('SELECT * FROM ai_historical_decisions WHERE decision_id=?',(did,)).fetchone())
                result=evaluate(decision,fetch_future(hist,context))
                db.execute('INSERT INTO ai_session_evaluations_v192 VALUES (?,?,?,?,?,?,?,?)',
                    (did,datetime.now().astimezone().isoformat(),result['outcome'],result['bars_checked'],result['exit_time_utc'],result['gross_pips_reference'],result['detail'],'M5_SESSION_CLOSE_1000_V192'))
                db.commit()
                with _lock:_state['last_message']=f"Guardada {action} · {result['outcome']} · {asof}"
                time.sleep(1)
    except Exception as e:
        with _lock:_state['last_error']=f'{type(e).__name__}: {str(e)[:350]}'
    finally:
        with _lock:_state['running']=False

def start_batch(max_calls,per_call_ceiling,max_estimated_usd):
    if not 1<=max_calls<=10:raise ValueError('Máximo 10 consultas por lote')
    if not 0<per_call_ceiling<=2.5 or not 0<max_estimated_usd<=2.5:raise ValueError('Cotas de presupuesto inválidas')
    if max_calls*per_call_ceiling>max_estimated_usd+1e-9:raise ValueError('La cota estimada excede el presupuesto del lote')
    if not os.getenv('GEMINI_API_KEY'):
        from dotenv import load_dotenv
        load_dotenv(ROOT/'backend'/'.env')
    if not os.getenv('GEMINI_API_KEY'):raise ValueError('GEMINI_API_KEY no configurada')
    if _load() is None:raise ValueError('Prepará primero el manifiesto')
    with _lock:
        if _state['running']:raise ValueError('Ya hay un lote ejecutándose')
        _state.update(running=True,attempted=0,last_error=None,last_message='Iniciando lote')
    threading.Thread(target=_run_batch,args=(max_calls,per_call_ceiling,max_estimated_usd),daemon=True).start()
    return status()
