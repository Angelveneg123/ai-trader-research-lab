"""V1.9: una decisión histórica Gemini, sin órdenes ni evaluación futura."""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / 'data' / 'historical.sqlite3'
JOURNAL = ROOT / 'data' / 'ai_decisions.sqlite3'
STEPS = {'M5': 300, 'M15': 900, 'H1': 3600}
COUNTS = {'M5': 60, 'M15': 40, 'H1': 30}
MODEL = 'gemini-3.1-flash-lite'


def read_context(path, asof=None):
    """asof is UTC timestamp of decision, exactly at the start of a new M5 candle."""
    db = sqlite3.connect(f'file:{Path(path).resolve().as_posix()}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        if asof is None:
            # Historical closed candle, selected without referencing subsequent prices.
            latest = db.execute("SELECT MAX(candle_time) FROM historical_candles WHERE symbol='EURUSD' AND timeframe='M5'").fetchone()[0]
            if latest is None:
                raise ValueError('No hay velas EURUSD M5')
            asof = latest + 300
        if asof % 300:
            raise ValueError('La fecha de decisión debe coincidir con apertura M5 UTC')
        local = datetime.fromtimestamp(asof, ZoneInfo('America/Managua'))
        if not (2 <= local.hour < 10):
            raise ValueError(f'Fuera de sesión 02:00–10:00 Managua: {local.isoformat()}. Usá --asof-utc para elegir otra fecha.')
        result = {'symbol': 'EURUSD', 'decision_time_utc': datetime.fromtimestamp(asof, timezone.utc).isoformat(), 'decision_time_managua': local.isoformat(), 'candles': {}}
        for tf, step in STEPS.items():
            # A candle is available only if its full period ended at or before asof.
            rows = db.execute('''SELECT candle_time,open,high,low,close,tick_volume FROM historical_candles
                WHERE symbol=? AND timeframe=? AND candle_time+?<=?
                ORDER BY candle_time DESC LIMIT ?''', ('EURUSD', tf, step, asof, COUNTS[tf])).fetchall()
            candles = [dict(row) for row in reversed(rows)]
            if len(candles) != COUNTS[tf]:
                raise ValueError(f'Histórico insuficiente para {tf}: {len(candles)}/{COUNTS[tf]}')
            # Reject gaps in recent M5 decision window; never fabricate candles.
            if tf == 'M5' and any(b['candle_time'] - a['candle_time'] != step for a, b in zip(candles, candles[1:])):
                raise ValueError('Las últimas 60 velas M5 contienen huecos; seleccioná otra fecha.')
            if candles[-1]['candle_time'] + step > asof:
                raise AssertionError('Se intentó usar una vela no cerrada')
            result['candles'][tf] = candles
        return result
    finally:
        db.close()


def init_journal(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ai_historical_decisions (
        decision_id TEXT PRIMARY KEY, created_at_utc TEXT NOT NULL,
        decision_time_utc TEXT NOT NULL, symbol TEXT NOT NULL,
        model TEXT NOT NULL, context_sha256 TEXT NOT NULL, context_json TEXT NOT NULL,
        decision TEXT NOT NULL, confidence REAL NOT NULL, reason TEXT NOT NULL,
        stop_loss REAL, take_profit REAL, raw_response_json TEXT NOT NULL,
        evaluation_status TEXT NOT NULL DEFAULT 'NOT_EVALUATED',
        UNIQUE(decision_time_utc,symbol,model,context_sha256))''')
    db.commit()


def validate_answer(answer, last_close):
    if not isinstance(answer, dict):
        raise ValueError('Gemini no devolvió un objeto JSON')
    action = answer.get('decision')
    if action not in ('BUY', 'SELL', 'WAIT'):
        raise ValueError('Decisión inválida')
    conf = answer.get('confidence')
    if isinstance(conf, bool) or not isinstance(conf, (float, int)) or not math.isfinite(conf) or not 0 <= conf <= 100:
        raise ValueError(f'Confianza inválida: {conf!r}. Se esperaba un número entre 0 y 1, o un porcentaje entre 1 y 100.')
    # La respuesta original se conserva intacta en raw_response_json.
    # Normalizar porcentajes numéricos, sin adivinar formatos de texto.
    if conf > 1:
        print(f'Normalizando confianza: {conf} / 100 = {conf / 100:.4f}')
        conf = conf / 100
    reason = answer.get('reason')
    if not isinstance(reason, str) or not 5 <= len(reason) <= 1000:
        raise ValueError('Justificación inválida')
    sl, tp = answer.get('stop_loss'), answer.get('take_profit')
    if action == 'WAIT':
        if sl is not None or tp is not None:
            raise ValueError('WAIT no debe incluir SL/TP')
    else:
        if not all(isinstance(x, (float, int)) and not isinstance(x, bool) and x > 0 for x in (sl, tp)):
            raise ValueError('BUY/SELL requiere SL y TP positivos')
        if action == 'BUY' and not (sl < last_close < tp):
            raise ValueError('SL/TP BUY no rodean el cierre de referencia')
        if action == 'SELL' and not (tp < last_close < sl):
            raise ValueError('SL/TP SELL no rodean el cierre de referencia')
    return action, float(conf), reason, sl, tp


def main():
    parser = argparse.ArgumentParser(description='Una consulta Gemini sobre EURUSD histórico, sin órdenes')
    parser.add_argument('--history', type=Path, default=HISTORY)
    parser.add_argument('--journal', type=Path, default=JOURNAL)
    parser.add_argument('--asof-utc', help='Ej: 2026-11-17T14:00:00+00:00; inicio de vela M5')
    parser.add_argument('--preview', action='store_true', help='No llama a Gemini ni escribe SQLite')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
    if not args.history.exists():
        raise SystemExit(f'No existe histórico: {args.history}. Copiá tu carpeta data anterior sin sobrescribirla.')
    ts = int(datetime.fromisoformat(args.asof_utc.replace('Z', '+00:00')).timestamp()) if args.asof_utc else None
    if ts is None:
        # Select the latest eligible session candle with sufficient history.
        with sqlite3.connect(f'file:{args.history.resolve().as_posix()}?mode=ro', uri=True) as db:
            times = [r[0] for r in db.execute("SELECT candle_time FROM historical_candles WHERE symbol='EURUSD' AND timeframe='M5' ORDER BY candle_time DESC LIMIT 2500")]
        context = None
        for t in times:
            try:
                context = read_context(args.history, t + 300)
                break
            except ValueError:
                continue
        if context is None:
            raise SystemExit('No se encontró una ventana histórica completa dentro de la sesión de Managua.')
    else:
        context = read_context(args.history, ts)
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    print('Escenario:', context['decision_time_utc'], '| EURUSD | M5/M15/H1 cerradas')
    print('Huella del contexto:', digest[:16])
    if args.preview:
        print('PREVIEW: no se realizó ninguna llamada ni escritura.')
        return
    key = os.getenv('GEMINI_API_KEY')
    if not key:
        raise SystemExit('Falta GEMINI_API_KEY en backend/.env')
    args.journal.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.journal)
    try:
        init_journal(db)
        existing = db.execute('SELECT decision,reason FROM ai_historical_decisions WHERE decision_time_utc=? AND symbol=? AND model=? AND context_sha256=?', (context['decision_time_utc'], 'EURUSD', MODEL, digest)).fetchone()
        if existing:
            print('Ya existe esta decisión; NO se repite consulta:', existing[0], existing[1])
            return
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30000))
        print('Consultando Gemini UNA vez...')
        from app.legacy_meter import generate_content
        response = generate_content(client,
            model=MODEL,
            contents=('Sos analista experimental. Los datos representan un instante histórico, no conocés el futuro. '
                      'Respondé BUY, SELL o WAIT. Ante incertidumbre elegí WAIT. '
                      'confidence DEBE ser un número entre 0 y 1 (ejemplo: 0.75, NO 75). '
                      'SL/TP se proponen respecto al último cierre M5, no como ejecución garantizada. '
                      'No calcules PnL en dólares ni inventes spreads, noticias o ticks. '
                      'Justificá brevemente con datos proporcionados. Contexto JSON: ' + payload),
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=500,
                response_mime_type='application/json',
                response_schema={
                    'type': 'OBJECT',
                    'properties': {
                        'decision': {'type': 'STRING', 'enum': ['BUY', 'SELL', 'WAIT']},
                        'confidence': {'type': 'NUMBER'},
                        'reason': {'type': 'STRING'},
                        'stop_loss': {'type': 'NUMBER', 'nullable': True},
                        'take_profit': {'type': 'NUMBER', 'nullable': True},
                    },
                    'required': ['decision', 'confidence', 'reason', 'stop_loss', 'take_profit'],
                },
            ),
        )
        raw_text = response.text or ''
        if not raw_text.strip():
            raise ValueError('Gemini devolvió una respuesta vacía')
        answer = json.loads(raw_text)
        print('RESPUESTA ORIGINAL DE GEMINI:')
        print(json.dumps(answer, ensure_ascii=False, indent=2))
        action, confidence, reason, sl, tp = validate_answer(answer, context['candles']['M5'][-1]['close'])
        db.execute('''INSERT INTO ai_historical_decisions
            (decision_id,created_at_utc,decision_time_utc,symbol,model,context_sha256,context_json,
             decision,confidence,reason,stop_loss,take_profit,raw_response_json)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
             (uuid.uuid4().hex, datetime.now(timezone.utc).isoformat(), context['decision_time_utc'],
              'EURUSD', MODEL, digest, payload, action, confidence, reason, sl, tp, json.dumps(answer, ensure_ascii=False)))
        db.commit()
        print(json.dumps({'saved': True, 'decision': action, 'confidence': confidence, 'reason': reason,
                          'stop_loss': sl, 'take_profit': tp, 'evaluation': 'NOT_EVALUATED',
                          'journal': str(args.journal), 'orders_sent': False}, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
