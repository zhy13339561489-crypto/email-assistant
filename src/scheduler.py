from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger


class EmailScheduler:
    def __init__(self, check_interval: int = 30, report_time: str = "09:00"):
        self.check_interval = check_interval
        self.report_time = report_time
        self.scheduler = BlockingScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
            }
        )

    def add_check_job(self, func, run_immediately: bool = True, **kwargs) -> None:
        self.scheduler.add_job(
            func,
            trigger=IntervalTrigger(minutes=self.check_interval),
            id="check_emails",
            name="定时检查新邮件",
            next_run_time=datetime.now() if run_immediately else None,
            replace_existing=True,
            **kwargs,
        )
        first_run = "启动后立即执行" if run_immediately else "等待下一个周期执行"
        logger.info(f"已添加新邮件检查任务，间隔 {self.check_interval} 分钟，{first_run}")

    def add_daily_report_job(self, func, **kwargs) -> None:
        hour, minute = self.report_time.split(":")
        self.scheduler.add_job(
            func,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_report",
            name="每日邮件报告",
            replace_existing=True,
            **kwargs,
        )
        logger.info(f"已添加每日报告任务，时间 {self.report_time}")

    def start(self) -> None:
        logger.info("调度器启动")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度器停止")

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)
