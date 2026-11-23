"""V1.9.3: lote piloto reproducible de decisiones históricas, SIN operaciones MT5."""
import argparse
import csv
import hashlib
import json
import os
import random
import sqlite3
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from primera_decision_gemini import read_context, validate_answer, init_journal, MODEL
from evaluar_sesion_v192 import evaluate

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo('America/Managua')
SCHEMA = {'type': 'OBJECT', 'properties': {
    'decision': {'type': 'STRING', 'enum': ['BUY', 'SELL', 'WAIT']},
    'confidence': {'type': 'NUMBER'}, 'reason': {'type': 'STRING'},
    'stop_loss': {'type': 'NUMBER', 'nullable': True},
    'take_profit': {'type': 'NUMBER', 'nullable': True}},
    'required': ['decision', 'confidence', 'reason', 'stop_loss', 'take_profit']}


def candidates(history, count, seed):
    """Deterministic selection by past timestamps, not future prices/outcomes.
    One sample per trading day; spread samples over local session hours.
    """
    with sqlite3.connect(f'file:{history.resolve().as_posix()}?mode=ro', uri=True) as db:
        times = [r[0] + 300 for r in db.execute(
            "SELECT candle_time FROM historical_candles WHERE symbol='EURUSD' AND timeframe='M5' ORDER BY candle_time")]
    groups = {}
    for ts in times:
        local = datetime.fromtimestamp(ts, TZ)
        if 2 <= local.hour < 10 and local.minute % 15 == 0:
            groups.setdefault(local.date().isoformat(), []).append(ts)
    rng = random.Random(seed)
    days = sorted(groups)
    rng.shuffle(days)
    selected = []
    # Balance hours by rotating a preferred hour across days; never use subsequent prices.
    for idx, day in enumerate(days):
        hour = 2 + idx % 8
        choices = [t for t in groups[day] if datetime.fromtimestamp(t, TZ).hour == hour]
        if not choices:
            choices = groups[day]
        rng.shuffle(choices)
        for ts in choices:
            try:
                context = read_context(history, ts)
                selected.append(context)
                break
            except ValueError:
                continue
        if len(selected) >= count:
            break
    return selected


def fetch_future(hist, context):
    ts = int(datetime.fromisoformat(context['decision_time_utc']).timestamp())
    return [dict(row) for row in hist.execute('''SELECT candle_time,open,high,low,close
        FROM historical_candles WHERE symbol='EURUSD' AND timeframe='M5'
        AND candle_time>=? ORDER BY candle_time LIMIT 100''', (ts,))]


def report(db, path):
    rows = [dict(r) for r in db.execute('''SELECT d.decision_time_utc,d.decision,d.confidence,d.stop_loss,d.take_profit,
        e.outcome,e.gross_pips_reference,e.bars_checked
        FROM ai_historical_decisions d LEFT JOIN ai_session_evaluations_v192 e ON e.decision_id=d.decision_id
        WHERE d.symbol='EURUSD' AND d.model=? ORDER BY d.decision_time_utc''', (MODEL,))]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['decision_time_utc','decision','confidence','stop_loss','take_profit','outcome','gross_pips_reference','bars_checked'])
        w.writeheader()
        w.writerows(rows)
    counts = Counter(r['decision'] for r in rows)
    outcomes = Counter(r['outcome'] or 'NOT_EVALUATED' for r in rows)
    buckets = {}
    for label, low, high in [('0-49%',0,.5),('50-69%',.5,.7),('70-84%',.7,.85),('85-100%',.85,1.00001)]:
        subset = [r for r in rows if low <= r['confidence'] < high]
        buckets[label] = {'total':len(subset),'outcomes':dict(Counter(r['outcome'] or 'NOT_EVALUATED' for r in subset))}
    closes = [r['gross_pips_reference'] for r in rows if r['outcome']=='SESSION_CLOSE' and r['gross_pips_reference'] is not None]
    summary = {'total':len(rows),'decisions':dict(counts),'outcomes':dict(outcomes),
               'confidence_buckets':buckets,'session_close_gross_pips_sum_reference':round(sum(closes),2),
               'session_close_count':len(closes),
               'warning':'Solo pips de cierres de sesión; no sumar con WIN/LOSS ni interpretar como PnL neto.'}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('CSV:',path)


def main():
    p = argparse.ArgumentParser(description='Piloto 10 o lote 100; SIN órdenes MT5')
    p.add_argument('--history',type=Path,default=ROOT/'data'/'historical.sqlite3')
    p.add_argument('--journal',type=Path,default=ROOT/'data'/'ai_decisions.sqlite3')
    p.add_argument('--count',type=int,default=10)
    p.add_argument('--seed',type=int,default=193)
    p.add_argument('--preview',action='store_true')
    p.add_argument('--max-new-calls',type=int,default=10)
    p.add_argument('--max-estimated-usd',type=float,default=2.50)
    p.add_argument('--usd-per-call-ceiling',type=float,default=None,help='Cota conservadora configurada manualmente; no es precio oficial')
    p.add_argument('--report-only',action='store_true')
    p.add_argument('--delay',type=float,default=3)
    args=p.parse_args()
    if not 1 <= args.count <= 100 or args.max_new_calls < 0 or args.delay < 0:
        p.error('count debe ser 1..100; max-new-calls y delay no negativos')
    if not args.history.is_file():
        p.error('No existe data/historical.sqlite3')
    if args.report_only:
        if not args.journal.is_file(): p.error('No existe el journal')
        with sqlite3.connect(args.journal) as db:
            db.row_factory=sqlite3.Row
            report(db, ROOT/'data'/'gemini_v193_report.csv')
        return
    contexts=candidates(args.history,args.count,args.seed)
    print(f'Escenarios seleccionados: {len(contexts)} de {args.count}; semilla {args.seed}')
    for c in contexts:
        print(c['decision_time_managua'], c['decision_time_utc'])
    if len(contexts)<args.count:
        print('AVISO: histórico insuficiente para el número solicitado; no se completará el lote.')
        return
    if args.preview:
        print('PREVIEW: sin API ni escrituras. La selección NO inspecciona precios futuros.')
        return
    if args.usd_per_call_ceiling is None or args.usd_per_call_ceiling <= 0:
        p.error('Para llamadas reales especificá --usd-per-call-ceiling con una cota conservadora en USD; es una estimación, NO garantía de gasto')
    if args.max_estimated_usd <= 0: p.error('Presupuesto inválido')
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent/'.env')
    key=os.getenv('GEMINI_API_KEY')
    if not key: p.error('Falta GEMINI_API_KEY en backend/.env')
    from google import genai
    from google.genai import types
    client=genai.Client(api_key=key,http_options=types.HttpOptions(timeout=30000))
    args.journal.parent.mkdir(parents=True,exist_ok=True)
    calls=0
    with sqlite3.connect(args.journal) as db, sqlite3.connect(f'file:{args.history.resolve().as_posix()}?mode=ro',uri=True) as hist:
        db.row_factory=sqlite3.Row
        hist.row_factory=sqlite3.Row
        init_journal(db)
        db.execute('''CREATE TABLE IF NOT EXISTS ai_session_evaluations_v192 (
            decision_id TEXT PRIMARY KEY, evaluated_at_utc TEXT NOT NULL,
            outcome TEXT NOT NULL, bars_checked INTEGER NOT NULL,
            exit_time_utc TEXT, gross_pips_reference REAL, detail TEXT NOT NULL,
            method TEXT NOT NULL)''')
        db.commit()
        for context in contexts:
            payload=json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            digest=hashlib.sha256(payload.encode()).hexdigest()
            existing=db.execute('''SELECT * FROM ai_historical_decisions WHERE decision_time_utc=? AND symbol='EURUSD'
                AND model=? AND context_sha256=?''',(context['decision_time_utc'],MODEL,digest)).fetchone()
            if existing:
                decision=dict(existing)
                print('Reutilizando decisión:',decision['decision_time_utc'])
            else:
                if calls >= args.max_new_calls or (calls+1)*args.usd_per_call_ceiling > args.max_estimated_usd:
                    print('LÍMITE alcanzado: sin más llamadas. Costo estimado máximo del lote:',round(calls*args.usd_per_call_ceiling,4),'USD')
                    break
                # Contar antes de la solicitud: un fallo también puede generar consumo.
                calls+=1
                print('Consulta',calls,'/',args.max_new_calls,context['decision_time_utc'])
                try:
                    from app.legacy_meter import generate_content
                    response=generate_content(client,
                        model=MODEL,
                        contents=('Analizá SOLO estas velas cerradas históricas, sin datos futuros. '
                                  'Elegí BUY, SELL o WAIT. Ante incertidumbre WAIT. '
                                  'confidence numérica 0..1, nunca porcentaje 0..100. '
                                  'SL y TP respecto al último cierre M5, o null ambos si WAIT. '
                                  'No inventes noticias, spread, ejecución ni resultados. '
                                  'Justificá usando exclusivamente los datos. Contexto: '+payload),
                        config=types.GenerateContentConfig(temperature=0,max_output_tokens=500,
                            response_mime_type='application/json',response_schema=SCHEMA))
                    answer=json.loads(response.text or '')
                    action,conf,reason,sl,tp=validate_answer(answer,context['candles']['M5'][-1]['close'])
                except Exception as exc:
                    print('ERROR API/VALIDACIÓN; lote detenido sin guardar decisión inválida:',type(exc).__name__,str(exc)[:400])
                    break
                did=uuid.uuid4().hex
                db.execute('''INSERT INTO ai_historical_decisions
                    (decision_id,created_at_utc,decision_time_utc,symbol,model,context_sha256,context_json,
                     decision,confidence,reason,stop_loss,take_profit,raw_response_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (did,datetime.now(timezone.utc).isoformat(),context['decision_time_utc'],'EURUSD',MODEL,digest,payload,
                     action,conf,reason,sl,tp,json.dumps(answer,ensure_ascii=False)))
                db.commit()
                decision=dict(db.execute('SELECT * FROM ai_historical_decisions WHERE decision_id=?',(did,)).fetchone())
                if args.delay: time.sleep(args.delay)
            if not db.execute('SELECT 1 FROM ai_session_evaluations_v192 WHERE decision_id=?',(decision['decision_id'],)).fetchone():
                outcome=evaluate(decision,fetch_future(hist,context))
                db.execute('''INSERT INTO ai_session_evaluations_v192 VALUES (?,?,?,?,?,?,?,?)''',
                    (decision['decision_id'],datetime.now(timezone.utc).isoformat(),outcome['outcome'],outcome['bars_checked'],
                     outcome['exit_time_utc'],outcome['gross_pips_reference'],outcome['detail'],'M5_SESSION_CLOSE_1000_V192'))
                db.commit()
                print('Resultado:',decision['decision'],outcome['outcome'],outcome['gross_pips_reference'])
        report(db,ROOT/'data'/'gemini_v193_report.csv')
        print('Solicitudes intentadas en esta ejecución:',calls)
        print('Estimación conservadora configurada:',round(calls*args.usd_per_call_ceiling,4),'USD; NO facturación verificada')
        print('orders_sent: false')

if __name__=='__main__':
    main()
