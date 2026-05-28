import argparse
import sys
from datetime import date
from pathlib import Path

from loguru import logger

from src.config import load_config
from src.fetcher import EmailFetcher
from src.preprocessor import EmailPreprocessor
from src.ai_engine import AIEngine
from src.storage import EmailStorage
from src.reporter import Reporter
from src.scheduler import EmailScheduler
from src.dashboard import run_dashboard


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
    storage = EmailStorage(config["database"]["path"])
    ai = AIEngine(
        api_key=config["openai"]["api_key"],
        model=config["openai"]["model"],
        base_url=config["openai"].get("base_url"),
        max_tokens=config["openai"]["max_tokens"],
        temperature=config["openai"]["temperature"],
        retry_count=config["processing"]["retry_count"],
        retry_delay=config["processing"]["retry_delay"],
        max_body_length=config["processing"]["max_body_length"],
        categories=config["categories"],
    )
    preprocessor = EmailPreprocessor(config["processing"]["max_body_length"])

    total_processed = 0

    for account_cfg in config["email_accounts"]:
        if not account_cfg.get("password"):
            logger.warning(f"账户 {account_cfg['name']} 未配置密码，跳过")
            continue

        logger.info(f"处理账户: {account_cfg['address']}")
        fetcher = EmailFetcher(
            address=account_cfg["address"],
            imap_server=account_cfg["imap_server"],
            imap_port=account_cfg["imap_port"],
            password=account_cfg["password"],
            use_ssl=account_cfg.get("use_ssl", True),
        )

        try:
            fetcher.connect()
            emails = fetcher.fetch_unread()

            if not emails:
                continue

            # 预处理
            for e in emails:
                preprocessor.process(e)

            # AI 处理
            results = ai.process_batch(emails)

            # 存储
            for email_data, result in results:
                storage.save_result(email_data, result, account=account_cfg["name"])
                logger.info(f"  [{result.classification.category}] {email_data.subject[:50]}")

            total_processed += len(results)
            logger.info(f"账户 {account_cfg['name']} 处理完成，共 {len(results)} 封")

        except Exception as e:
            logger.error(f"处理账户 {account_cfg['name']} 失败: {e}")
        finally:
            fetcher.disconnect()

    return total_processed


def generate_report(config: dict, report_type: str = "daily") -> str:
    """生成报告"""
    storage = EmailStorage(config["database"]["path"])
    reporter = Reporter(storage)

    if report_type == "weekly":
        return reporter.weekly_report()
    return reporter.daily_report()


def show_stats(config: dict, days: int = 30) -> str:
    """显示统计信息"""
    storage = EmailStorage(config["database"]["path"])
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


def run_daemon(config: dict) -> None:
    """后台定时运行"""
    scheduler = EmailScheduler(
        check_interval=config["schedule"]["check_interval_minutes"],
        report_time=config["schedule"]["daily_report_time"],
    )
    scheduler.add_check_job(process_emails, args=[config])
    scheduler.add_daily_report_job(
        lambda: logger.info(f"\n{generate_report(config)}")
    )
    logger.info("进入后台模式，按 Ctrl+C 退出")
    scheduler.start()


def main():
    parser = argparse.ArgumentParser(description="Email AI 自动整理工具")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("process", help="处理新邮件")
    sub.add_parser("report", help="生成今日报告")
    report_weekly = sub.add_parser("report-weekly", help="生成周报")
    stats_parser = sub.add_parser("stats", help="查看统计")
    stats_parser.add_argument("--days", type=int, default=30, help="统计天数")
    sub.add_parser("daemon", help="后台定时运行")
    dashboard_parser = sub.add_parser("dashboard", help="启动邮件处理结果页面")
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    dashboard_parser.add_argument("--port", type=int, default=8765, help="监听端口")

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
        run_daemon(config)
    elif args.command == "dashboard":
        run_dashboard(
            db_path=config["database"]["path"],
            host=args.host,
            port=args.port,
        )


if __name__ == "__main__":
    main()
