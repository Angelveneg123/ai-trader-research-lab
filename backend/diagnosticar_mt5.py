"""Diagnóstico de solo lectura del terminal MT5 y de las velas cerradas."""
import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone

from dotenv.parser import parse_stream

from app.market_symbols import ENV_PATH, load_settings
from app.mt5_connection import MT5Unavailable, connection, installations
from app.mt5_market import SECONDS, closed_candles, session_status, unavailable_status


def check_env(path):
    try:
        with path.open(encoding="utf-8-sig") as stream:
            bad = [binding.original.line for binding in parse_stream(stream) if binding.error]
    except FileNotFoundError:
        return {"estado": "ausente", "lineas_invalidas": []}
    except (OSError, UnicodeError):
        return {"estado": "ilegible", "lineas_invalidas": []}
    return {"estado": "invalido" if bad else "ok", "lineas_invalidas": bad}


def output(result, code):
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", help="Ruta exacta al terminal64.exe que ya tenés abierto")
    parser.add_argument("--symbol", default="EURUSDmicro")
    parser.add_argument("--timeout-ms", type=int, default=60000,
                        help="Espera de inicialización en milisegundos, entre 1000 y 120000")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--sin-env", action="store_true", help="Ignora el archivo .env para aislar la conexión")
    modes.add_argument("--solo-env", action="store_true", help="Revisa sintaxis sin imprimir valores ni iniciar MT5")
    args = parser.parse_args()
    if not 1000 <= args.timeout_ms <= 120000:
        parser.error("--timeout-ms debe estar entre 1000 y 120000")
    env = {"estado": "omitido", "lineas_invalidas": []} if args.sin_env else check_env(ENV_PATH)
    result = {"modo": "solo_lectura", "plataforma": platform.system(), "python": platform.python_version(),
              "hora_utc": datetime.now(timezone.utc).isoformat(), "env": env}
    if env["estado"] in ("invalido", "ilegible"):
        return output(result, 4)
    if args.solo_env:
        return output(result, 0)
    if not args.sin_env:
        load_settings()
    result["instalaciones_detectadas"] = len(installations())
    result["timeout_configurado_ms"] = args.timeout_ms
    print(f"Conectando con MT5 en modo lectura (timeout configurado: {args.timeout_ms / 1000:g} s)...",
          file=sys.stderr, flush=True)
    started = time.monotonic()
    code = 0
    try:
        with connection(executable=args.terminal, retries=0, timeout_ms=args.timeout_ms, load_env=False) as (
            mt5, account, terminal
        ):
            status = session_status(account, terminal)
            result["mt5"] = {key: value for key, value in status.items() if key not in ("balance", "equity")}
            try:
                bar = closed_candles(mt5, args.symbol, "M5", 2)[-1]
                result["vela"] = {"simbolo": args.symbol, "cierre_utc": datetime.fromtimestamp(
                    bar["time"] + SECONDS["M5"], timezone.utc).isoformat(), "close": bar["close"]}
            except MT5Unavailable as exc:
                result["error_vela"] = {"codigo": exc.code, "mensaje": str(exc)}
                code = 3
    except MT5Unavailable as exc:
        result["mt5"] = {key: value for key, value in unavailable_status(exc).items() if key not in ("balance", "equity")}
        code = 2
    result["duracion_ms"] = round((time.monotonic() - started) * 1000)
    return output(result, code)


if __name__ == "__main__":
    sys.exit(main())
