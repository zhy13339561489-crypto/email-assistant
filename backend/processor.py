from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger

from ai_engine import AIEngine
from src.fetcher import EmailFetcher
from src.preprocessor import EmailPreprocessor

from .storage import MySQLEmailStorage, _mailbox_for_category


class EmailProcessingService:
    def __init__(
        self,
        config: dict,
        storage: MySQLEmailStorage | None = None,
        ai: AIEngine | None = None,
    ):
        self.config = config
        self.storage = storage or MySQLEmailStorage.from_config(config)
        self.ai = ai or self._build_ai()
        self.preprocessor = EmailPreprocessor(config["processing"]["max_body_length"])

    def _build_ai(self) -> AIEngine:
        openai_cfg = self.config["openai"]
        processing_cfg = self.config["processing"]
        return AIEngine(
            api_key=openai_cfg["api_key"],
            model=openai_cfg["model"],
            review_model=openai_cfg.get("review_model"),
            base_url=openai_cfg.get("base_url"),
            max_tokens=openai_cfg["max_tokens"],
            temperature=openai_cfg["temperature"],
            retry_count=processing_cfg["retry_count"],
            retry_delay=processing_cfg["retry_delay"],
            max_body_length=processing_cfg["max_body_length"],
            categories=self.config["categories"],
            reply_review_rounds=int(processing_cfg.get("reply_review_rounds", 3)),
        )

    def process_emails(self) -> int:
        total_processed = 0
        for account_cfg in self.config["email_accounts"]:
            total_processed += self._process_account(account_cfg)
        return total_processed

    def process_window(self, start: datetime, end: datetime) -> int:
        total_processed = 0
        for account_cfg in self.config["email_accounts"]:
            total_processed += self._process_account_window(account_cfg, start, end)
        return total_processed

    def backfill_originals(self, days: int = 30) -> int:
        end = datetime.now().replace(microsecond=0) + timedelta(seconds=1)
        start = end - timedelta(days=max(1, days))
        total_updated = 0
        for account_cfg in self.config["email_accounts"]:
            total_updated += self._backfill_account_originals(account_cfg, start, end)
        return total_updated

    def generate_daily_report(self, end_at: datetime | None = None) -> dict:
        window_end = end_at or datetime.now().replace(second=0, microsecond=0)
        window_start = window_end - timedelta(days=1)
        logger.info(f"开始生成邮件日报: {window_start} ~ {window_end}")

        processed = self.process_window(window_start, window_end)
        emails = self.storage.get_emails_between(window_start, window_end)
        content = self.ai.generate_daily_report(
            emails,
            start_at=window_start.strftime("%Y-%m-%d %H:%M"),
            end_at=window_end.strftime("%Y-%m-%d %H:%M"),
        )
        report_id = self.storage.save_daily_report(
            report_date=window_end.date(),
            window_start=window_start,
            window_end=window_end,
            email_count=len(emails),
            content=content,
        )
        logger.info(
            f"邮件日报生成完成: report_id={report_id}, 新处理 {processed} 封，报告包含 {len(emails)} 封"
        )
        return {
            "report_id": report_id,
            "processed": processed,
            "email_count": len(emails),
            "window_start": window_start.isoformat(timespec="seconds"),
            "window_end": window_end.isoformat(timespec="seconds"),
            "content": content,
        }

    def _process_account(self, account_cfg: dict) -> int:
        if not account_cfg.get("password"):
            logger.warning(f"账户 {account_cfg['name']} 未配置密码，跳过")
            return 0

        logger.info(f"检查账户新邮件: {account_cfg['address']}")
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
                logger.info(f"账户 {account_cfg['name']} 暂无未读新邮件")
                return 0

            for email_data in emails:
                self.preprocessor.process(email_data)

            results = self.ai.process_batch(emails)
            for email_data, result in results:
                email_id = self.storage.save_result(email_data, result, account=account_cfg["name"])
                self._prepare_reply_review(email_id, email_data, result)
                logger.info(f"  [{result.classification.category}] {email_data.subject[:50]}")

            logger.info(f"账户 {account_cfg['name']} 处理完成，共 {len(results)} 封")
            return len(results)
        except Exception as e:
            logger.error(f"处理账户 {account_cfg['name']} 失败: {e}")
            return 0
        finally:
            fetcher.disconnect()

    def _backfill_account_originals(self, account_cfg: dict, start: datetime, end: datetime) -> int:
        if not account_cfg.get("password"):
            logger.warning(f"Account {account_cfg['name']} has no password, skip original backfill")
            return 0

        fetcher = EmailFetcher(
            address=account_cfg["address"],
            imap_server=account_cfg["imap_server"],
            imap_port=account_cfg["imap_port"],
            password=account_cfg["password"],
            use_ssl=account_cfg.get("use_ssl", True),
        )

        try:
            fetcher.connect()
            updated = 0
            for email_data in fetcher.fetch_between(start, end):
                if not self.storage.original_fields_missing(email_data.uid, account=account_cfg["name"]):
                    continue
                updated += self.storage.update_original_fields(email_data, account=account_cfg["name"])
            logger.info(f"Account {account_cfg['name']} original backfill updated {updated} emails")
            return updated
        except Exception as e:
            logger.error(f"Account {account_cfg['name']} original backfill failed: {e}")
            return 0
        finally:
            fetcher.disconnect()

    def _process_account_window(self, account_cfg: dict, start: datetime, end: datetime) -> int:
        if not account_cfg.get("password"):
            logger.warning(f"账户 {account_cfg['name']} 未配置密码，跳过")
            return 0

        logger.info(f"检查账户时间窗口邮件: {account_cfg['address']} ({start} ~ {end})")
        fetcher = EmailFetcher(
            address=account_cfg["address"],
            imap_server=account_cfg["imap_server"],
            imap_port=account_cfg["imap_port"],
            password=account_cfg["password"],
            use_ssl=account_cfg.get("use_ssl", True),
        )

        try:
            fetcher.connect()
            emails = fetcher.fetch_between(start, end)
            new_emails = [
                email_data
                for email_data in emails
                if not self.storage.has_email(email_data.uid, account=account_cfg["name"])
            ]
            if not new_emails:
                logger.info(f"账户 {account_cfg['name']} 时间窗口内没有未处理邮件")
                return 0

            for email_data in new_emails:
                self.preprocessor.process(email_data)

            results = self.ai.process_batch(new_emails)
            for email_data, result in results:
                email_id = self.storage.save_result(email_data, result, account=account_cfg["name"])
                self._prepare_reply_review(email_id, email_data, result)
                logger.info(f"  [{result.classification.category}] {email_data.subject[:50]}")
            return len(results)
        except Exception as e:
            logger.error(f"处理账户 {account_cfg['name']} 时间窗口邮件失败: {e}")
            return 0
        finally:
            fetcher.disconnect()

    def _prepare_reply_review(self, email_id: int, email_data, result) -> None:
        try:
            if _mailbox_for_category(result.classification.category) == "spam":
                self.storage.save_reply_decision(
                    email_id,
                    needs_reply=False,
                    reason="垃圾邮件不需要自动回复",
                    status="not_required",
                )
                return

            decision = self.ai.decide_reply(email_data, result)
            if not decision.needs_reply:
                self.storage.save_reply_decision(
                    email_id,
                    needs_reply=False,
                    reason=decision.reason,
                    status="not_required",
                )
                return

            draft = self.ai.draft_reply(email_data, result)
            draft = self.ai.refine_reply_with_reviewer(
                _email_record(email_data, result),
                draft,
            )
            self.storage.save_reply_decision(
                email_id,
                needs_reply=True,
                reason=decision.reason,
                draft_subject=draft.subject,
                draft_body=draft.body,
                ai_review_notes=draft.reviewer_notes,
                ai_review_rounds=draft.review_rounds,
                ai_review_passed=draft.review_passed,
                status="pending_review",
            )
        except Exception as e:
            logger.error(f"Reply routing failed for email_id={email_id}: {e}")
            self.storage.save_reply_decision(
                email_id,
                needs_reply=False,
                reason=f"自动回复路由失败: {e}",
                status="route_failed",
            )


def _email_record(email_data, result) -> dict:
    return {
        "sender": email_data.sender,
        "sender_name": email_data.sender_name,
        "recipient": email_data.to,
        "subject": email_data.subject,
        "date": email_data.date.isoformat(timespec="seconds") if hasattr(email_data.date, "isoformat") else str(email_data.date),
        "summary": result.summary,
        "raw_body_text": email_data.raw_body_text or email_data.body_text,
        "body_text": email_data.body_text,
    }
