import json
import mimetypes
import sqlite3
from datetime import datetime, timedelta
from email.header import decode_header
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from loguru import logger


PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


class DashboardData:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_dashboard(self, days: int = 30, category: str = "all", query: str = "") -> dict:
        days = max(1, min(days, 365))
        category = category.strip()
        query = query.strip()
        since = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_conn() as conn:
            emails = self._get_emails(conn, since, category, query)
            action_items = self._get_action_items(conn, since)
            category_counts = self._get_category_counts(conn, since)
            top_senders = self._get_top_senders(conn, since)

        total = len(emails)
        with_actions = sum(1 for item in emails if item["action_count"] > 0)
        avg_confidence = (
            round(sum(item["confidence"] or 0 for item in emails) / total, 3)
            if total
            else 0
        )
        attachment_count = sum(1 for item in emails if item["has_attachments"])

        return {
            "meta": {
                "days": days,
                "category": category or "all",
                "query": query,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
            "stats": {
                "total": total,
                "with_actions": with_actions,
                "avg_confidence": avg_confidence,
                "attachments": attachment_count,
            },
            "categories": category_counts,
            "top_senders": top_senders,
            "action_items": action_items,
            "emails": emails,
        }

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_emails(
        self,
        conn: sqlite3.Connection,
        since: str,
        category: str,
        query: str,
    ) -> list[dict]:
        filters = ["e.date >= ?"]
        params: list[str] = [since]

        if category and category != "all":
            filters.append("e.category = ?")
            params.append(category)

        if query:
            like = f"%{query}%"
            filters.append(
                "(e.subject LIKE ? OR e.summary LIKE ? OR e.sender LIKE ? OR e.sender_name LIKE ?)"
            )
            params.extend([like, like, like, like])

        rows = conn.execute(
            f"""
            SELECT
                e.*,
                COUNT(a.id) AS action_count,
                GROUP_CONCAT(a.action, ' || ') AS action_preview
            FROM emails e
            LEFT JOIN action_items a ON a.email_id = e.id
            WHERE {" AND ".join(filters)}
            GROUP BY e.id
            ORDER BY e.date DESC
            LIMIT 200
            """,
            params,
        ).fetchall()

        return [self._normalize_email(row) for row in rows]

    def _get_action_items(self, conn: sqlite3.Connection, since: str) -> list[dict]:
        rows = conn.execute(
            """
            SELECT
                a.id,
                a.email_id,
                a.action,
                a.deadline,
                a.priority,
                e.subject,
                e.sender,
                e.sender_name,
                e.category,
                e.date
            FROM action_items a
            JOIN emails e ON a.email_id = e.id
            WHERE e.date >= ?
            ORDER BY
                CASE a.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                e.date DESC
            LIMIT 100
            """,
            (since,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "email_id": row["email_id"],
                "action": row["action"] or "",
                "deadline": row["deadline"] or "",
                "priority": row["priority"] or "normal",
                "subject": row["subject"] or "",
                "sender": row["sender"] or "",
                "sender_name": _decode_mime_words(row["sender_name"] or row["sender"] or ""),
                "category": row["category"] or "未分类",
                "date": row["date"] or "",
            }
            for row in rows
        ]

    def _get_category_counts(self, conn: sqlite3.Connection, since: str) -> list[dict]:
        rows = conn.execute(
            """
            SELECT category, COUNT(*) AS count
            FROM emails
            WHERE date >= ?
            GROUP BY category
            ORDER BY count DESC, category ASC
            """,
            (since,),
        ).fetchall()
        return [
            {"category": row["category"] or "未分类", "count": row["count"]}
            for row in rows
        ]

    def _get_top_senders(self, conn: sqlite3.Connection, since: str) -> list[dict]:
        rows = conn.execute(
            """
            SELECT sender_name, sender, COUNT(*) AS count
            FROM emails
            WHERE date >= ?
            GROUP BY sender
            ORDER BY count DESC
            LIMIT 8
            """,
            (since,),
        ).fetchall()
        return [
            {
                "name": _decode_mime_words(row["sender_name"] or row["sender"] or ""),
                "email": row["sender"] or "",
                "count": row["count"],
            }
            for row in rows
        ]

    def _normalize_email(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "uid": row["uid"] or "",
            "account": row["account"] or "",
            "sender": row["sender"] or "",
            "sender_name": _decode_mime_words(row["sender_name"] or row["sender"] or ""),
            "subject": row["subject"] or "(无主题)",
            "date": row["date"] or "",
            "category": row["category"] or "未分类",
            "confidence": row["confidence"] or 0,
            "category_reason": row["category_reason"] or "",
            "summary": row["summary"] or "",
            "has_attachments": bool(row["has_attachments"]),
            "processed_at": row["processed_at"] or "",
            "action_count": row["action_count"] or 0,
            "action_preview": row["action_preview"] or "",
        }


def make_dashboard_handler(db_path: str, static_dir: Path = FRONTEND_DIR):
    data_source = DashboardData(db_path)
    static_dir = Path(static_dir)

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/dashboard":
                self._send_dashboard_data(parsed.query)
                return
            self._send_static_file(parsed.path)

        def log_message(self, fmt: str, *args) -> None:
            logger.debug("Dashboard: " + fmt, *args)

        def _send_dashboard_data(self, query_string: str) -> None:
            params = parse_qs(query_string)
            days = _parse_int(params.get("days", ["30"])[0], default=30)
            category = params.get("category", ["all"])[0]
            query = params.get("q", [""])[0]
            payload = data_source.get_dashboard(days=days, category=category, query=query)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static_file(self, request_path: str) -> None:
            target = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
            file_path = (static_dir / target).resolve()

            if static_dir.resolve() not in file_path.parents and file_path != static_dir.resolve():
                self.send_error(403)
                return
            if not file_path.exists() or not file_path.is_file():
                file_path = static_dir / "index.html"

            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def run_dashboard(db_path: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    if not FRONTEND_DIR.exists():
        raise RuntimeError(f"前端目录不存在: {FRONTEND_DIR}")
    server = ThreadingHTTPServer((host, port), make_dashboard_handler(db_path))
    logger.info(f"邮件处理结果页面已启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在停止邮件处理结果页面")
    finally:
        server.server_close()


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decode_mime_words(value: str) -> str:
    if not value:
        return ""

    decoded = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def make_server_args(config: dict) -> SimpleNamespace:
    return SimpleNamespace(db_path=config["database"]["path"], host="127.0.0.1", port=8765)
