"""计划任务入口：守护单个应用子进程，合并输出并轮转日志。"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "runtime-logs"
LOGS.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(LOGS / "service.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
log = logging.getLogger("supervisor")
log.setLevel(logging.INFO)
log.addHandler(handler)

while True:
    log.info("Starting FastAPI")
    child = subprocess.Popen([sys.executable, "-u", "-c", "import logging; logging.basicConfig(level=logging.INFO); from backend.cli import main; raise SystemExit(main(['serve']))"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
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
