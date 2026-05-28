from __future__ import annotations

import json
import mimetypes
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from .mailer import SMTPReplyMailer
from .processor import EmailProcessingService
from .storage import MySQLEmailStorage


PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


class BackendRuntime:
    def __init__(self, config: dict):
        self.config = config
        self.storage = MySQLEmailStorage.from_config(config)
        self.processor = EmailProcessingService(config, storage=self.storage)
        self.mailer = SMTPReplyMailer()
        self.process_lock = threading.Lock()
        self.reply_lock = threading.Lock()
        self.last_process: dict = {
            "running": False,
            "processed": 0,
            "started_at": "",
            "finished_at": "",
            "error": "",
        }
        self.report_lock = threading.Lock()
        self.last_report: dict = {
            "running": False,
            "report_id": "",
            "email_count": 0,
            "started_at": "",
            "finished_at": "",
            "error": "",
        }
        self.last_backfill: dict = {
            "running": False,
            "updated": 0,
            "started_at": "",
            "finished_at": "",
            "error": "",
        }

    def dashboard(self, days: int, category: str, query: str, mailbox: str = "inbox") -> dict:
        return self.storage.get_dashboard(
            days=days,
            category=category,
            query=query,
            mailbox=mailbox,
        )

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

    def generate_daily_report(self) -> dict:
        if not self.report_lock.acquire(blocking=False):
            return {"running": True, "message": "已有日报任务正在运行", **self.last_report}

        self.last_report = {
            "running": True,
            "report_id": "",
            "email_count": 0,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": "",
            "error": "",
        }
        try:
            report = self.processor.generate_daily_report(
                end_at=datetime.now().replace(second=0, microsecond=0)
            )
            self.last_report.update(
                {
                    "running": False,
                    "report_id": report["report_id"],
                    "email_count": report["email_count"],
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": "",
                }
            )
            return {"running": False, "message": "日报生成完成", **self.last_report, "report": report}
        except Exception as e:
            logger.exception(f"邮件日报任务失败: {e}")
            self.last_report.update(
                {
                    "running": False,
                    "report_id": "",
                    "email_count": 0,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": str(e),
                }
            )
            return {"running": False, "message": "日报生成失败", **self.last_report}
        finally:
            self.report_lock.release()

    def latest_daily_report(self) -> dict:
        return {"report": self.storage.get_latest_daily_report()}

    def backfill_originals(self, days: int = 30) -> dict:
        if not self.process_lock.acquire(blocking=False):
            return {"running": True, "message": "已有邮件任务正在运行", **self.last_backfill}

        self.last_backfill = {
            "running": True,
            "updated": 0,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": "",
            "error": "",
        }
        try:
            updated = self.processor.backfill_originals(days=days)
            self.last_backfill.update(
                {
                    "running": False,
                    "updated": updated,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": "",
                }
            )
            return {"running": False, "message": "原始邮件信息补采完成", **self.last_backfill}
        except Exception as e:
            logger.exception(f"原始邮件信息补采任务失败: {e}")
            self.last_backfill.update(
                {
                    "running": False,
                    "updated": 0,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": str(e),
                }
            )
            return {"running": False, "message": "原始邮件信息补采失败", **self.last_backfill}
        finally:
            self.process_lock.release()

    def save_reply_draft(self, reply_id: int, payload: dict) -> dict:
        updated = self.storage.update_reply_draft(
            reply_id=reply_id,
            subject=str(payload.get("subject") or ""),
            body=str(payload.get("body") or ""),
            reviewer_notes=str(payload.get("reviewer_notes") or ""),
            status="pending_review",
        )
        return {"ok": updated, "message": "草稿已保存" if updated else "草稿不存在或已发送"}

    def revise_reply(self, reply_id: int, payload: dict) -> dict:
        reply = self.storage.get_reply_with_email(reply_id)
        if not reply:
            return {"ok": False, "error": "回复草稿不存在"}

        notes = str(payload.get("reviewer_notes") or "").strip()
        if not notes:
            return {"ok": False, "error": "请填写修改意见"}

        current_subject = str(payload.get("subject") or reply.get("reply_subject") or "")
        current_body = str(payload.get("body") or reply.get("reply_body") or "")
        draft = self.processor.ai.revise_reply(reply, current_subject, current_body, notes)
        self.storage.update_reply_draft(
            reply_id=reply_id,
            subject=draft.subject,
            body=draft.body,
            reviewer_notes=notes,
            status="pending_review",
        )
        return {"ok": True, "message": "AI 已根据意见改写", "subject": draft.subject, "body": draft.body}

    def send_reply(self, reply_id: int, payload: dict) -> dict:
        if not self.reply_lock.acquire(blocking=False):
            return {"ok": False, "error": "已有回复发送任务正在运行"}
        try:
            if "subject" in payload or "body" in payload:
                self.storage.update_reply_draft(
                    reply_id=reply_id,
                    subject=str(payload.get("subject") or ""),
                    body=str(payload.get("body") or ""),
                    reviewer_notes=str(payload.get("reviewer_notes") or ""),
                    status="pending_review",
                )

            reply = self.storage.get_reply_with_email(reply_id)
            if not reply:
                return {"ok": False, "error": "回复草稿不存在"}
            if not reply.get("reply_needs_reply"):
                return {"ok": False, "error": "该邮件被判定为无需回复"}
            if reply.get("reply_status") == "sent":
                return {"ok": False, "error": "该回复已经发送"}
            if not reply.get("reply_subject") or not reply.get("reply_body"):
                return {"ok": False, "error": "回复主题或正文为空"}

            account_cfg = self._account_config(reply.get("account") or "")
            if not account_cfg:
                return {"ok": False, "error": "找不到对应邮箱账号配置"}

            self.storage.mark_reply_sending(reply_id)
            try:
                self.mailer.send_reply(account_cfg, reply)
            except Exception as e:
                self.storage.mark_reply_send_failed(reply_id, str(e))
                return {"ok": False, "error": f"发送失败: {e}"}

            self.storage.mark_reply_sent(reply_id)
            return {"ok": True, "message": "回复邮件已发送"}
        finally:
            self.reply_lock.release()

    def _account_config(self, account_name: str) -> dict | None:
        for account in self.config.get("email_accounts", []):
            if account.get("name") == account_name:
                return account
        return None

    def delete_email(self, email_id: int) -> dict:
        deleted = self.storage.soft_delete_email(email_id)
        return {"ok": deleted, "message": "邮件已删除" if deleted else "邮件不存在或已删除"}

    def delete_action_item(self, action_id: int) -> dict:
        deleted = self.storage.soft_delete_action_item(action_id)
        return {"ok": deleted, "message": "待办事项已删除" if deleted else "待办事项不存在或已删除"}

    def health(self) -> dict:
        return {
            "ok": True,
            "database": "mysql",
            "last_process": self.last_process,
            "last_report": self.last_report,
            "last_backfill": self.last_backfill,
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
                        mailbox=params.get("mailbox", ["inbox"])[0],
                    )
                )
                return
            if parsed.path == "/api/spam":
                params = parse_qs(parsed.query)
                self._send_json(
                    runtime.dashboard(
                        days=_parse_int(params.get("days", ["30"])[0], 30),
                        category="all",
                        query=params.get("q", [""])[0],
                        mailbox="spam",
                    )
                )
                return
            if parsed.path == "/api/reports/latest":
                self._send_json(runtime.latest_daily_report())
                return
            self._send_static(parsed.path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/process":
                self._send_json(runtime.process_now())
                return
            if parsed.path == "/api/reports/daily":
                self._send_json(runtime.generate_daily_report())
                return
            if parsed.path == "/api/backfill-originals":
                params = parse_qs(parsed.query)
                self._send_json(
                    runtime.backfill_originals(
                        days=_parse_int(params.get("days", ["30"])[0], 30),
                    )
                )
                return
            delete_action = _parse_delete_action(parsed.path)
            if delete_action:
                item_id, item_type = delete_action
                if item_type == "email":
                    self._send_json(runtime.delete_email(item_id))
                    return
                if item_type == "action":
                    self._send_json(runtime.delete_action_item(item_id))
                    return
            reply_action = _parse_reply_action(parsed.path)
            if reply_action:
                reply_id, action = reply_action
                payload = self._read_json()
                if action == "save":
                    self._send_json(runtime.save_reply_draft(reply_id, payload))
                    return
                if action == "revise":
                    self._send_json(runtime.revise_reply(reply_id, payload))
                    return
                if action == "send":
                    self._send_json(runtime.send_reply(reply_id, payload))
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

        def _read_json(self) -> dict:
            length = _parse_int(self.headers.get("Content-Length", "0"), 0)
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError:
                return {}

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
        logger.info(f"自动邮件处理已启动：每 {interval} 分钟检查一次，启动后立即执行")

        report_hour, report_minute = _parse_report_time(config["schedule"].get("daily_report_time", "17:00"))
        scheduler.add_job(
            runtime.generate_daily_report,
            trigger=CronTrigger(hour=report_hour, minute=report_minute),
            id="daily_ai_report",
            name="AI 每日邮件汇总报告",
            replace_existing=True,
        )
        logger.info(f"AI 邮件日报已启动：每天 {report_hour:02d}:{report_minute:02d} 生成")

        scheduler.start()

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


def _parse_reply_action(path: str) -> tuple[int, str] | None:
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "api" or parts[1] != "replies":
        return None
    try:
        reply_id = int(parts[2])
    except ValueError:
        return None
    if parts[3] not in {"save", "revise", "send"}:
        return None
    return reply_id, parts[3]


def _parse_delete_action(path: str) -> tuple[int, str] | None:
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "api" or parts[3] != "delete":
        return None
    if parts[1] == "emails":
        item_type = "email"
    elif parts[1] == "actions":
        item_type = "action"
    else:
        return None
    try:
        item_id = int(parts[2])
    except ValueError:
        return None
    return item_id, item_type


def _parse_report_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        return int(hour_text), int(minute_text)
    except (AttributeError, ValueError):
        return 17, 0
