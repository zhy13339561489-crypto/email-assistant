import argparse
import sys
from datetime import date
from pathlib import Path

from loguru import logger

from src.config import load_config
from src.reporter import Reporter
from backend import EmailProcessingService, MySQLEmailStorage, run_backend


def setup_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    logger.remove()
    logger.add(sys.stderr, level=log_cfg.get("level", "INFO"))
    log_file = log_cfg.get("file")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        logger.add(log_file, level="DEBUG", rotation="10 MB")


def process_emails(config: dict) -> int:
    """处理新邮件，返回处理数量"""
    return EmailProcessingService(config).process_emails()


def generate_report(config: dict, report_type: str = "daily") -> str:
    """生成报告"""
    storage = MySQLEmailStorage.from_config(config)
    reporter = Reporter(storage)

    if report_type == "weekly":
        return reporter.weekly_report()
    return reporter.daily_report()


def show_stats(config: dict, days: int = 30) -> str:
    """显示统计信息"""
    storage = MySQLEmailStorage.from_config(config)
    stats = storage.get_stats(days=days)

    lines = [
        f"📊 邮件统计 (最近 {days} 天)",
        "=" * 40,
        f"总数: {stats['total']}",
        "",
    ]

    if stats["by_category"]:
        lines.append("分类分布:")
        for cat, count in stats["by_category"].items():
            pct = count / stats["total"] * 100 if stats["total"] else 0
            lines.append(f"  {cat:<10} {count:>4} ({pct:.1f}%)")

    if stats["top_senders"]:
        lines.append("\n高频发件人:")
        for s in stats["top_senders"][:5]:
            lines.append(f"  {s['name'] or s['email']:<20} {s['count']} 封")

    return "\n".join(lines)


def run_daemon(config: dict, interval_minutes: int | None = None) -> None:
    """持续检查新邮件并自动处理"""
    run_backend(config, interval_minutes=interval_minutes, auto_process=True)


def main():
    parser = argparse.ArgumentParser(description="Email AI 自动整理工具")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("process", help="处理新邮件")
    sub.add_parser("report", help="生成今日报告")
    report_weekly = sub.add_parser("report-weekly", help="生成周报")
    stats_parser = sub.add_parser("stats", help="查看统计")
    stats_parser.add_argument("--days", type=int, default=30, help="统计天数")
    daemon_parser = sub.add_parser("daemon", help="常驻后端：提供 API，并自动检查处理新邮件")
    daemon_parser.add_argument("--interval", type=int, help="检查间隔分钟数，默认读取 config.yaml")
    daemon_parser.add_argument("--host", default="127.0.0.1", help="后端监听地址")
    daemon_parser.add_argument("--port", type=int, default=8765, help="后端监听端口")
    daemon_parser.add_argument("--no-auto", action="store_true", help="只启动 API，不自动轮询邮箱")
    backend_parser = sub.add_parser("backend", help="启动后端服务")
    backend_parser.add_argument("--interval", type=int, help="检查间隔分钟数，默认读取 config.yaml")
    backend_parser.add_argument("--host", default="127.0.0.1", help="后端监听地址")
    backend_parser.add_argument("--port", type=int, default=8765, help="后端监听端口")
    backend_parser.add_argument("--no-auto", action="store_true", help="只启动 API，不自动轮询邮箱")
    watch_parser = sub.add_parser("watch", help="backend 的别名：常驻监听新邮件")
    watch_parser.add_argument("--interval", type=int, help="检查间隔分钟数，默认读取 config.yaml")
    watch_parser.add_argument("--host", default="127.0.0.1", help="后端监听地址")
    watch_parser.add_argument("--port", type=int, default=8765, help="后端监听端口")
    watch_parser.add_argument("--no-auto", action="store_true", help="只启动 API，不自动轮询邮箱")
    dashboard_parser = sub.add_parser("dashboard", help="启动后端服务并展示前端页面")
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    dashboard_parser.add_argument("--port", type=int, default=8765, help="监听端口")
    dashboard_parser.add_argument("--no-auto", action="store_true", help="只启动 API，不自动轮询邮箱")

    args = parser.parse_args()
    config = load_config(args.config)
    setup_logging(config)

    if args.command == "process" or args.command is None:
        count = process_emails(config)
        logger.info(f"处理完成，共处理 {count} 封邮件")
    elif args.command == "report":
        print(generate_report(config))
    elif args.command == "report-weekly":
        print(generate_report(config, "weekly"))
    elif args.command == "stats":
        print(show_stats(config, args.days))
    elif args.command == "daemon":
        run_backend(
            config,
            host=args.host,
            port=args.port,
            interval_minutes=args.interval,
            auto_process=not args.no_auto,
        )
    elif args.command == "backend":
        run_backend(
            config,
            host=args.host,
            port=args.port,
            interval_minutes=args.interval,
            auto_process=not args.no_auto,
        )
    elif args.command == "watch":
        run_backend(
            config,
            host=args.host,
            port=args.port,
            interval_minutes=args.interval,
            auto_process=not args.no_auto,
        )
    elif args.command == "dashboard":
        run_backend(
            config,
            host=args.host,
            port=args.port,
            auto_process=not args.no_auto,
        )


if __name__ == "__main__":
    main()
