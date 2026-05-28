from __future__ import annotations

import json
import mimetypes
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from .processor import EmailProcessingService
from .storage import MySQLEmailStorage


PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


class BackendRuntime:
    def __init__(self, config: dict):
        self.config = config
        self.storage = MySQLEmailStorage.from_config(config)
        self.processor = EmailProcessingService(config, storage=self.storage)
        self.process_lock = threading.Lock()
        self.last_process: dict = {
            "running": False,
            "processed": 0,
            "started_at": "",
            "finished_at": "",
            "error": "",
        }

    def dashboard(self, days: int, category: str, query: str) -> dict:
        return self.storage.get_dashboard(days=days, category=category, query=query)

    def process_now(self) -> dict:
        if not self.process_lock.acquire(blocking=False):
            return {"running": True, "message": "已有邮件处理任务正在运行", **self.last_process}

        self.last_process = {
            "running": True,
            "processed": 0,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": "",
            "error": "",
        }
        try:
            processed = self.processor.process_emails()
            self.last_process.update(
                {
                    "running": False,
                    "processed": processed,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": "",
                }
            )
            return {"running": False, "message": "处理完成", **self.last_process}
        except Exception as e:
            logger.exception(f"邮件处理任务失败: {e}")
            self.last_process.update(
                {
                    "running": False,
                    "processed": 0,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": str(e),
                }
            )
            return {"running": False, "message": "处理失败", **self.last_process}
        finally:
            self.process_lock.release()

    def health(self) -> dict:
        return {
            "ok": True,
            "database": "mysql",
            "last_process": self.last_process,
        }


def make_handler(runtime: BackendRuntime, static_dir: Path = FRONTEND_DIR):
    static_dir = Path(static_dir)

    class BackendHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self._send_json(runtime.health())
                return
            if parsed.path == "/api/dashboard":
                params = parse_qs(parsed.query)
                self._send_json(
                    runtime.dashboard(
                        days=_parse_int(params.get("days", ["30"])[0], 30),
                        category=params.get("category", ["all"])[0],
                        query=params.get("q", [""])[0],
                    )
                )
                return
            self._send_static(parsed.path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/process":
                self._send_json(runtime.process_now())
                return
            self.send_error(404)

        def log_message(self, fmt: str, *args) -> None:
            logger.debug("Backend: " + fmt, *args)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, request_path: str) -> None:
            target = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
            file_path = (static_dir / target).resolve()
            static_root = static_dir.resolve()
            if static_root not in file_path.parents and file_path != static_root:
                self.send_error(403)
                return
            if not file_path.exists() or not file_path.is_file():
                file_path = static_root / "index.html"
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return BackendHandler


def run_backend(
    config: dict,
    host: str = "127.0.0.1",
    port: int = 8765,
    interval_minutes: int | None = None,
    auto_process: bool = True,
) -> None:
    runtime = BackendRuntime(config)
    interval = interval_minutes or config["schedule"]["check_interval_minutes"]
    scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
        }
    )
    if auto_process:
        scheduler.add_job(
            runtime.process_now,
            trigger=IntervalTrigger(minutes=interval),
            id="process_new_emails",
            name="自动检查并处理新邮件",
            next_run_time=datetime.now(),
            replace_existing=True,
        )
        scheduler.start()
        logger.info(f"自动邮件处理已启动：每 {interval} 分钟检查一次，启动后立即执行")

    server = ThreadingHTTPServer((host, port), make_handler(runtime))
    logger.info(f"后端服务已启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在停止后端服务")
    finally:
        scheduler.shutdown(wait=False)
        server.server_close()


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
