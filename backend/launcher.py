"""JobPilot desktop launcher.

Starts the local server, opens it in a standalone app window (Edge/Chrome --app mode, own profile),
and shuts the server down when that window is closed.

    pythonw backend\\launcher.py            normal use (no console window)
    python  backend\\launcher.py --check    start, verify the API answers, stop (exit code 0 = ok)
"""
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import truststore  # noqa: E402

truststore.inject_into_ssl()

from app.config import ROOT, get_settings  # noqa: E402

PREFERRED_PORT = 8000
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def setup_logging() -> None:
    log = get_settings().data_dir / "jobpilot.log"
    if sys.stdout is None or sys.stderr is None:  # pythonw has no console
        f = open(log, "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(log, encoding="utf-8"), logging.StreamHandler(sys.stderr)])


def alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/status", timeout=1.5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def pick_port() -> int:
    if port_free(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_window(url: str) -> subprocess.Popen | None:
    profile = get_settings().data_dir / "browser-profile"
    for exe in BROWSERS:
        if Path(exe).exists():
            return subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1440,920",
                                     "--no-first-run", "--no-default-browser-check"])
    import webbrowser
    webbrowser.open(url)
    return None


def main() -> int:
    check = "--check" in sys.argv
    setup_logging()
    log = logging.getLogger("jobpilot.launcher")
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        msg = "UI not built. Run install-app.ps1 (or: cd frontend; npm run build)."
        log.error(msg)
        print(msg, file=sys.stderr)
        return 2

    if alive(PREFERRED_PORT):  # already running → just open another window onto it
        log.info("JobPilot already running; attaching")
        if not check:
            p = open_window(f"http://127.0.0.1:{PREFERRED_PORT}")
            if p:
                p.wait()
        return 0

    import uvicorn

    from app.main import app
    port = pick_port()
    url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, log_level="info"))
    result = {"code": 1}

    def watch():
        for _ in range(120):
            if alive(port):
                break
            time.sleep(0.5)
        else:
            server.should_exit = True
            return
        if check:
            result["code"] = 0
            server.should_exit = True
            return
        proc = open_window(url)
        if proc:
            proc.wait()  # blocks until the app window is closed
            server.should_exit = True

    threading.Thread(target=watch, daemon=True).start()
    log.info("starting JobPilot at %s", url)
    server.run()
    return result["code"] if check else 0


if __name__ == "__main__":
    sys.exit(main())
