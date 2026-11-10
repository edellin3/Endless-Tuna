"""Local supervisor: API, frontend and durable worker; no shell or external calls."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from endless_tuna import config  # load only this application's .env


def port(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise ValueError('Ports must be between 1024 and 65535.')
    return number


def stop_children(children, timeout=120):
    for child in reversed(children):
        if child.poll() is None:
            try: os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError: pass
    deadline = time.monotonic() + timeout
    for child in reversed(children):
        try: child.wait(timeout=max(.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            print('Shutdown grace period exceeded; remaining job leases recover on next start.', flush=True)
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--built', action='store_true', help='Serve the built frontend from the API instead of Vite')
    args = parser.parse_args()
    children = []
    stopped = False
    def request_stop(*_):
        nonlocal stopped
        stopped = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)
    try:
        if not (3, 11) <= sys.version_info[:2] <= (3, 13):
            raise ValueError('Supported Python versions: 3.11–3.13.')
        api_port = port(os.getenv('TUNA_API_PORT', '8000'))
        ui_port = port(os.getenv('TUNA_UI_PORT', '5173'))
        if not args.built and api_port == ui_port:
            raise ValueError('API and frontend ports must differ.')
        for value in ([api_port] if args.built else [api_port, ui_port]):
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try: sock.bind(('127.0.0.1', value))
                except OSError: raise ValueError(f'Local port {value} is in use; stop its server or choose TUNA_API_PORT/TUNA_UI_PORT.') from None
        import sqlite3
        with sqlite3.connect(':memory:') as con:
            con.execute('CREATE VIRTUAL TABLE probe USING fts5(text)')
        npm = shutil.which('npm')
        if not args.built:
            if not npm or not (ROOT / 'frontend/node_modules/vite/bin/vite.js').exists():
                raise ValueError('Node/npm or frontend dependencies missing. Run npm ci in endless-tuna/frontend.')
            node = shutil.which('node')
            if not node: raise ValueError('Node is missing from PATH; activate the supported Node installation.')
            version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
            major, minor, *_ = [int(v) for v in version.split('.')]
            if not (major == 22 and minor >= 12 or major == 24):
                raise ValueError('Supported Node versions: 22.12+ (22.x) or 24.x; .nvmrc selects 24.')
        elif not (ROOT / 'frontend/dist/index.html').exists():
            raise ValueError('Built frontend missing. Run npm run build in endless-tuna/frontend first.')
        def launch(command, cwd, env=None):
            child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
            children.append(child)
            return child
        backend = ROOT / 'backend'
        api = launch([sys.executable, '-m', 'uvicorn', 'endless_tuna.main:app', '--host', '127.0.0.1', '--port', str(api_port)], backend)
        deadline = time.monotonic() + 30
        while not stopped:
            if api.poll() is not None: raise ValueError('Backend exited during startup; inspect its output above.')
            try:
                with urlopen(f'http://127.0.0.1:{api_port}/api/health', timeout=1) as response:
                    if response.status == 200: break
            except (URLError, TimeoutError): pass
            if time.monotonic() > deadline: raise ValueError('Backend did not become ready within 30 seconds.')
            time.sleep(.1)
        if stopped: return 0
        launch([sys.executable, '-m', 'endless_tuna.worker'], backend)
        if not args.built:
            frontend_env = {k: v for k, v in os.environ.items() if not k.startswith('LAS_') and k not in ('OPENAI_KEY', 'OPENAI_API_KEY')}
            frontend_env['TUNA_API_PORT'] = str(api_port)
            launch([npm, 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(ui_port), '--strictPort'], ROOT / 'frontend', frontend_env)
        print(f'endless tuna: http://127.0.0.1:{api_port if args.built else ui_port} — Ctrl-C stops all services.', flush=True)
        while not stopped:
            if any(child.poll() is not None for child in children):
                raise ValueError('A service exited; stopping the other services. Inspect output above.')
            time.sleep(.2)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Startup errors contain local diagnostics only, never environment values or keys.
        print(f'Startup failed: {error}', file=sys.stderr)
        return 1
    finally:
        stop_children(children)


if __name__ == '__main__':
    raise SystemExit(main())
