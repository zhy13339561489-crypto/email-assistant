from __future__ import annotations

from loguru import logger

from ai_engine import AIEngine
from src.fetcher import EmailFetcher
from src.preprocessor import EmailPreprocessor

from .storage import MySQLEmailStorage


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
            base_url=openai_cfg.get("base_url"),
            max_tokens=openai_cfg["max_tokens"],
            temperature=openai_cfg["temperature"],
            retry_count=processing_cfg["retry_count"],
            retry_delay=processing_cfg["retry_delay"],
            max_body_length=processing_cfg["max_body_length"],
            categories=self.config["categories"],
        )

    def process_emails(self) -> int:
        total_processed = 0
        for account_cfg in self.config["email_accounts"]:
            total_processed += self._process_account(account_cfg)
        return total_processed

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
                self.storage.save_result(email_data, result, account=account_cfg["name"])
                logger.info(f"  [{result.classification.category}] {email_data.subject[:50]}")

            logger.info(f"账户 {account_cfg['name']} 处理完成，共 {len(results)} 封")
            return len(results)
        except Exception as e:
            logger.error(f"处理账户 {account_cfg['name']} 失败: {e}")
            return 0
        finally:
            fetcher.disconnect()
