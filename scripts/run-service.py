"""计划任务入口：守护单个应用子进程，合并输出并轮转日志。"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "runtime-logs"
LOGS.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(LOGS / "service.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
log = logging.getLogger("supervisor")
log.setLevel(logging.INFO)
log.addHandler(handler)

HOST = '127.0.0.1'
PORT = 8000
HEALTH_INTERVAL = 10
HEALTH_TIMEOUT = 3
STARTUP_GRACE = 30
MAX_HEALTH_FAILURES = 3


def health_watchdog(child: subprocess.Popen[str], started_at: float) -> None:
    """Restart a live but unresponsive child so a hung service cannot persist forever."""
    failures = 0
    while child.poll() is None:
        time.sleep(HEALTH_INTERVAL)
        if child.poll() is not None:
            return
        if time.monotonic() - started_at < STARTUP_GRACE:
            continue
        try:
            with urlopen(f'http://{HOST}:{PORT}/health', timeout=HEALTH_TIMEOUT) as response:
                healthy = response.status == 200
        except (OSError, URLError):
            healthy = False
        if healthy:
            if failures:
                log.info('Health check recovered after failures=%s', failures)
            failures = 0
            continue
        failures += 1
        log.warning('Health check failed failures=%s/%s', failures, MAX_HEALTH_FAILURES)
        if failures >= MAX_HEALTH_FAILURES:
            log.error('FastAPI unresponsive; terminating child for restart')
            child.terminate()
            return

while True:
    log.info("Starting FastAPI")
    child = subprocess.Popen([sys.executable, "-u", "-c", "import logging; logging.basicConfig(level=logging.INFO); from backend.cli import main; raise SystemExit(main(['serve']))"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    watchdog = threading.Thread(target=health_watchdog, args=(child, time.monotonic()), daemon=True)
    watchdog.start()
    try:
        for line in child.stdout:
            log.info(line.rstrip())
        code = child.wait()
        log.info("FastAPI exited code=%s; restarting in 5 seconds", code)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait()
    time.sleep(5)
