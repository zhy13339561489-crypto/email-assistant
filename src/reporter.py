from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from .storage import EmailStorage


class Reporter:
    def __init__(self, storage: EmailStorage):
        self.storage = storage
        self.template_dir = Path(__file__).parent.parent / "templates"

    def daily_report(self, report_date: date | None = None) -> str:
        if report_date is None:
            report_date = date.today()

        emails = self.storage.get_today_emails()
        action_items = self.storage.get_action_items(days=1)
        stats = self.storage.get_stats(days=1)

        lines = [
            f"📊 邮件日报 - {report_date.strftime('%Y-%m-%d')}",
            "=" * 50,
            "",
            f"📬 今日共处理 {stats['total']} 封邮件",
            "",
        ]

        # 分类统计
        if stats["by_category"]:
            lines.append("📁 分类统计:")
            for cat, count in stats["by_category"].items():
                bar = "█" * min(count, 20)
                lines.append(f"  {cat:<8} {bar} {count}")
            lines.append("")

        # 重要邮件摘要
        important = [e for e in emails if e.get("category") in ("重要紧急", "工作")]
        if important:
            lines.append("⚡ 重要邮件:")
            for e in important[:10]:
                lines.append(f"  [{e['category']}] {e['sender_name']}: {e['subject']}")
                if e.get("summary"):
                    lines.append(f"    → {e['summary'][:100]}")
            lines.append("")

        # 待办事项
        if action_items:
            lines.append("✅ 待办事项:")
            for item in action_items:
                priority_mark = "🔴" if item["priority"] == "high" else "🟡"
                deadline = f" (截止: {item['deadline']})" if item.get("deadline") else ""
                lines.append(f"  {priority_mark} {item['action']}{deadline}")
                lines.append(f"    来自: {item.get('subject', '')}")
            lines.append("")

        # 全部邮件列表
        if emails:
            lines.append("📋 全部邮件:")
            for e in emails:
                lines.append(f"  [{e.get('category', '未分类')}] {e['sender_name']}: {e['subject']}")
            lines.append("")

        return "\n".join(lines)

    def weekly_report(self, end_date: date | None = None) -> str:
        if end_date is None:
            end_date = date.today()
        start_date = end_date - timedelta(days=7)

        stats = self.storage.get_stats(days=7)

        lines = [
            f"📊 邮件周报 - {start_date} ~ {end_date}",
            "=" * 50,
            "",
            f"📬 本周共处理 {stats['total']} 封邮件",
            "",
        ]

        if stats["by_category"]:
            lines.append("📁 分类统计:")
            for cat, count in stats["by_category"].items():
                bar = "█" * min(count, 30)
                lines.append(f"  {cat:<8} {bar} {count}")
            lines.append("")

        if stats["top_senders"]:
            lines.append("👤 高频发件人:")
            for s in stats["top_senders"][:5]:
                lines.append(f"  {s['name'] or s['email']}: {s['count']} 封")
            lines.append("")

        return "\n".join(lines)

    def to_html(self, report_text: str, title: str = "邮件报告") -> str:
        template_path = self.template_dir / "daily_report.html"
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
        else:
            template = self._default_template()

        html_body = report_text.replace("\n", "<br>").replace(" ", "&nbsp;")
        return template.replace("{{title}}", title).replace("{{content}}", html_body)

    def _default_template(self) -> str:
        return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{{title}}</title>
<style>body{font-family:sans-serif;max-width:800px;margin:40px auto;padding:20px;background:#f5f5f5}
.report{background:white;padding:30px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}
h1{color:#333;border-bottom:2px solid #4CAF50;padding-bottom:10px}</style>
</head><body><div class="report"><h1>{{title}}</h1><div>{{content}}</div></div></body></html>"""
