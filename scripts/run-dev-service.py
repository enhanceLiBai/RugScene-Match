"""启动与稳定服务并行的开发后端，共用当前数据库。"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEV_ROOT = ROOT / "dev-runtime"
PYTHON = ROOT / ".ven" / "Scripts" / "python.exe"
DEV_PORT = 8001


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    command = [str(PYTHON), "-u", "-c", f"import logging; logging.basicConfig(level=logging.INFO); from backend.cli import main; raise SystemExit(main(['serve', '--host', '127.0.0.1', '--port', '{DEV_PORT}']))"]
    logging.info("启动开发服务：http://127.0.0.1:%s（共用当前数据库）", DEV_PORT)
    child = subprocess.Popen(command, cwd=DEV_ROOT)
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
