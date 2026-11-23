"""Abre el panel y la API de observación en una sola dirección local."""

import argparse
import errno
import os
import socket
import sys
import webbrowser

import uvicorn

from app.market_symbols import load_settings
from app.mt5_connection import MT5Unavailable, terminal_path

HOST = "127.0.0.1"
PREFERRED_PORT = 8001
FALLBACK_PORT = 8002
PORT_UNAVAILABLE = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}


def reserve_listener():
    for port in (PREFERRED_PORT, FALLBACK_PORT, 0):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((HOST, port))
            listener.listen()
        except OSError as exc:
            listener.close()
            code = getattr(exc, "winerror", None) or exc.errno
            if port == 0 or code not in PORT_UNAVAILABLE:
                raise
        else:
            return listener


class DashboardServer(uvicorn.Server):
    def __init__(self, config, *, open_browser):
        super().__init__(config)
        self.open_browser = open_browser

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if not self.started:
            return
        url = f"http://{self.config.host}:{self.config.port}/"
        print(f"Panel listo: {url}", flush=True)
        if self.open_browser:
            try:
                if webbrowser.open(url):
                    return
            except (OSError, webbrowser.Error):
                pass
            print("Abrí la dirección del panel en tu navegador.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", help="Ruta al terminal64.exe que ya tiene Deriv demo abierto")
    parser.add_argument("--sin-navegador", action="store_true", help="Muestra el enlace en la consola")
    args = parser.parse_args(argv)

    load_settings()
    if args.terminal:
        os.environ["MT5_TERMINAL_PATH"] = args.terminal
    try:
        selected = terminal_path()
        print(f"Terminal MT5: {selected or 'detección de MetaTrader5'}", flush=True)
    except MT5Unavailable as exc:
        print(f"MT5 pendiente. {exc}", flush=True)

    try:
        listener = reserve_listener()
    except OSError as exc:
        print(f"No se pudo abrir un puerto local. {exc}", file=sys.stderr)
        return 1

    with listener:
        from app.main import DASHBOARD_DIST, app

        if not (DASHBOARD_DIST / "index.html").is_file():
            print("Falta el panel compilado en frontend/dist. Extraé el ZIP completo.", file=sys.stderr)
            return 1
        port = listener.getsockname()[1]
        if port != PREFERRED_PORT:
            print(f"Puerto {PREFERRED_PORT} no disponible. Usando el puerto {port}.", flush=True)
        config = uvicorn.Config(app, host=HOST, port=port, workers=1, lifespan="on")
        server = DashboardServer(config, open_browser=not args.sin_navegador)
        server.run(sockets=[listener])
    return 0 if server.started else 1


if __name__ == "__main__":
    sys.exit(main())
