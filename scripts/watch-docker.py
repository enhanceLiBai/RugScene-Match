"""One bounded Docker/database check, invoked every minute by Task Scheduler."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
LOGS = ROOT / "runtime-logs"


def run(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    LOGS.mkdir(exist_ok=True)
    handler = RotatingFileHandler(LOGS / "docker-watch.log", maxBytes=1024 * 1024,
                                  backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log = logging.getLogger("docker-watch")
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    try:
        engine = run([DOCKER, "info", "--format", "{{.ServerVersion}}"])
        if engine.returncode:
            # Desktop must run as the signed-in Windows user, not SYSTEM.
            result = run(["powershell.exe", "-NoProfile", "-Command",
                "if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) { "
                "Start-Process -FilePath 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe' -WindowStyle Hidden; "
                "Write-Output 'Started Docker Desktop' } else { Write-Output 'Desktop running; engine not ready' }"])
            log.warning("Engine unavailable; %s", result.stdout.strip() or "Desktop launch failed")
            return 1
        state = run([DOCKER, "inspect", "--format", "{{.State.Running}}", "pgvector"])
        if state.returncode:
            log.error("Database container pgvector not found; no container was created")
            return 1
        if state.stdout.strip() != "true":
            started = run([DOCKER, "start", "pgvector"], timeout=40)
            if started.returncode:
                log.error("Failed to start pgvector")
                return 1
            log.info("Started existing pgvector database container")
        ready = run([DOCKER, "exec", "pgvector", "pg_isready", "-q"])
        if ready.returncode:
            log.warning("Database is not ready yet")
            return 1
        return 0
    except subprocess.TimeoutExpired:
        log.error("Docker command timed out; retry on next scheduled check")
        return 1
    except OSError as exc:
        log.error("Watchdog could not run: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
