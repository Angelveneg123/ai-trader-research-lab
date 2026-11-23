
# AI_TRADER_AUTO_LOAD_ENV
from pathlib import Path as _Path
import os as _os

_env = _Path(__file__).resolve().parent / ".env"

if _env.is_file():
    for _linea in _env.read_text(encoding="utf-8-sig").splitlines():
        _linea = _linea.strip()

        if not _linea or _linea.startswith("#") or "=" not in _linea:
            continue

        _clave, _valor = _linea.split("=", 1)
        _clave = _clave.strip()
        _valor = _valor.strip().strip('"').strip("'")

        if _clave in (
            "TELEGRAM_ENABLED",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID"
        ):
            _os.environ[_clave] = _valor

"""Telegram notifications from persisted prospective events; no MT5 orders or API model calls."""
import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.prospective_store import db_path


def send_message(token, chat, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat, "text": message[:4000]}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            answer = json.load(res)
        if not answer.get("ok"):
            raise RuntimeError("Telegram rechazó el mensaje")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Telegram HTTP {exc.code}") from None


def init(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS telegram_event_outbox (
      event_key TEXT PRIMARY KEY, body TEXT NOT NULL, created_utc TEXT NOT NULL,
      sent_utc TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)""")
    conn.commit()


def enqueue(conn, key, body):
    conn.execute("INSERT OR IGNORE INTO telegram_event_outbox(event_key,body,created_utc) VALUES (?,?,?)",
                 (key, body, datetime.now(timezone.utc).isoformat()))


def collect_events(conn, include_wait=False):
    conn.row_factory = sqlite3.Row
    decisions = conn.execute("""SELECT d.*,c.symbol,c.m5_closed_utc,e.status AS execution_status
      FROM prospective_decisions d JOIN prospective_cycles c ON c.cycle_id=d.cycle_id
      LEFT JOIN prospective_demo_entries e ON e.cycle_id=d.cycle_id
      ORDER BY d.received_utc""").fetchall()
    for r in decisions:
        if r['action'] == 'WAIT' and not include_wait:
            continue
        mode = "DECISIÓN IA (NO CONFIRMADA COMO ORDEN)"
        if r['execution_status']:
            mode += f"\nEstado ejecutor demo: {r['execution_status']}"
        valid = 'válida para evaluación' if r['valid'] else 'rechazada por validación'
        msg = (f"🤖 AI Trader | {mode}\n{r['provider'].upper()} · {r['symbol']} · {r['action']}\n"
               f"Vela M5: {r['m5_closed_utc']}\nValidación: {valid}\n"
               f"SL: {r['sl'] if r['sl'] is not None else '—'} | TP: {r['tp'] if r['tp'] is not None else '—'}\n"
               f"Motivo: {r['reason'][:650]}\nNota: {r['risk_note'][:250]}")
        enqueue(conn, f"decision:{r['cycle_id']}:{r['provider']}", msg)
    outcomes = conn.execute("""SELECT o.*,c.symbol,d.action FROM prospective_outcomes o
      JOIN prospective_cycles c ON c.cycle_id=o.cycle_id
      JOIN prospective_decisions d ON d.cycle_id=o.cycle_id AND d.provider=o.provider
      ORDER BY o.evaluated_utc""").fetchall()
    for r in outcomes:
        net = f"{r['net_pips']:+.2f} pips estimados" if r['net_pips'] is not None else 'No evaluable'
        msg = (f"📊 AI Trader | RESULTADO SIMULADO\n{r['provider'].upper()} · {r['symbol']} · {r['action']}\n"
               f"Resultado: {r['outcome']}\n{net}\nDetalle: {r['detail'][:600]}\n"
               "No es P/L confirmado en cuenta MT5 demo.")
        enqueue(conn, f"outcome:{r['cycle_id']}:{r['provider']}", msg)
    deals = conn.execute("""SELECT * FROM prospective_demo_deals ORDER BY happened_utc""").fetchall()
    for r in deals:
        msg = (f"💼 AI Trader | DEAL MT5 DEMO REGISTRADO\n{r['symbol']} · ticket {r['ticket']}\n"
               f"{'Entrada' if r['entry'] == 0 else 'Movimiento/salida'} · volumen {r['volume']}\n"
               f"Precio {r['price']} · resultado neto registrado USD {r['net_usd']:+.2f}\n"
               "Confirmar el estado de la posición en MT5.")
        enqueue(conn, f"deal:{r['account']}:{r['ticket']}", msg)
    conn.commit()


def flush(conn, token, chat, max_events=30):
    rows = conn.execute("SELECT event_key,body,attempts FROM telegram_event_outbox WHERE sent_utc IS NULL AND attempts<8 ORDER BY created_utc,event_key LIMIT ?", (max_events,)).fetchall()
    for key, body, attempts in rows:
        try:
            send_message(token, chat, body)
            conn.execute("UPDATE telegram_event_outbox SET sent_utc=?,attempts=attempts+1,last_error=NULL WHERE event_key=?",
                         (datetime.now(timezone.utc).isoformat(), key))
            print('Enviado:', key, flush=True)
        except Exception as exc:
            conn.execute("UPDATE telegram_event_outbox SET attempts=attempts+1,last_error=? WHERE event_key=?", (str(exc)[:180], key))
            print('Telegram pendiente:', str(exc), flush=True)
            conn.commit()
            break
        conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Envía mensaje de prueba sin leer eventos')
    parser.add_argument('--once', action='store_true', help='Procesa eventos y termina')
    parser.add_argument('--include-wait', action='store_true', help='También notifica WAIT')
    parser.add_argument('--poll-seconds', type=int, default=15)
    parser.add_argument('--backfill', action='store_true', help='Envía también eventos antiguos')
    args = parser.parse_args()
    if os.getenv('TELEGRAM_ENABLED') != '1':
        parser.error('TELEGRAM_ENABLED debe ser 1')
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    chat = os.getenv('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat:
        parser.error('Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID')
    if args.test:
        send_message(token, chat, '✅ AI Trader V2.5: Telegram conectado. Prueba sin operaciones.')
        print('Mensaje de prueba enviado')
        return
    path = Path(db_path())
    if not path.exists():
        parser.error(f'No existe la base de datos: {path}')
    conn = sqlite3.connect(str(path), timeout=20)
    init(conn)
    if not args.backfill:
        count = conn.execute('SELECT COUNT(*) FROM telegram_event_outbox').fetchone()[0]
        if count == 0:
            collect_events(conn, include_wait=True)
            conn.execute('UPDATE telegram_event_outbox SET sent_utc=? WHERE sent_utc IS NULL',
                         (datetime.now(timezone.utc).isoformat(),))
            conn.commit()
            print('Historial anterior marcado como leído; solo se avisarán eventos nuevos.', flush=True)
    while True:
        try:
            collect_events(conn, include_wait=args.include_wait)
            flush(conn, token, chat)
        except sqlite3.Error as exc:
            print('Error SQLite:', exc, flush=True)
        if args.once:
            break
        time.sleep(max(5, args.poll_seconds))


if __name__ == '__main__':
    main()
