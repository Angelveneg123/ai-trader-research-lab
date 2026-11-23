"""Prueba el arranque local y el panel con MT5 y Gemini simulados."""
import argparse
import os
import re
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory


def ready_url(api, log_path):
    deadline = time.monotonic() + 12
    while api.poll() is None and time.monotonic() < deadline:
        log = log_path.read_text(encoding="utf-8", errors="replace")
        ready = re.search(r"Panel listo: (http://127\.0\.0\.1:(\d+)/)", log)
        if ready:
            return ready[1], int(ready[2])
        time.sleep(.10)
    raise RuntimeError("El panel simulado no arrancó dentro del plazo.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocupar", type=int, nargs="+", choices=(8001, 8002), default=[])
    args = parser.parse_args()
    occupied = set(args.ocupar)
    open_ports = [port for port in (8001, 8002) if port not in occupied]
    with ExitStack() as resources:
        for port in sorted(occupied):
            listener = resources.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen()
        print(f"Puertos ocupados por la prueba: {sorted(occupied)}", flush=True)

        tmp = resources.enter_context(TemporaryDirectory(prefix="prueba_arranque_"))
        log_path = Path(tmp) / "servidor.txt"
        log = resources.enter_context(log_path.open("w", encoding="utf-8"))
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHON_DOTENV_DISABLED": "1"}
        with subprocess.Popen([sys.executable, "evidencias/servir_fixture_ui.py"],
                              stdout=log, stderr=subprocess.STDOUT, env=env) as api:
            try:
                url, port = ready_url(api, log_path)
                assert port not in occupied
                if open_ports:
                    assert port == open_ports[0]
                print(f"URL anunciada por el servidor: {url}", flush=True)
                subprocess.run(
                    ["node", "evidencias/comprobar_dom.cjs"], check=True, timeout=20,
                    env={**env, "UI_TEST_URL": url, "UI_TEST_OUTPUT": tmp},
                )
                assert api.poll() is None
            finally:
                api.terminate()
                api.wait(timeout=15)
                print(log_path.read_text(encoding="utf-8", errors="replace"), end="")


if __name__ == "__main__":
    main()
