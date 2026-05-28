import re

from loguru import logger

from .models import EmailData


SIGNATURE_MARKERS = [
    "-- \n", "--\n", "—",
    "Best regards,", "Best Regards,", "BR,",
    "Sent from my", "发自我的",
    "此致", "祝好", "谢谢",
]

FORWARD_MARKERS = [
    "---------- Forwarded message",
    "------ Original Message ------",
    "On .* wrote:",
]


class EmailPreprocessor:
    def __init__(self, max_body_length: int = 2000):
        self.max_body_length = max_body_length

    def clean_text(self, text: str) -> str:
        if not text:
            return ""

        # 移除签名
        for marker in SIGNATURE_MARKERS:
            idx = text.find(marker)
            if idx > 0:
                text = text[:idx]

        # 移除转发标记后的内容（保留前面的回复内容）
        for pattern in FORWARD_MARKERS:
            text = re.split(pattern, text, maxsplit=1)[0]

        # 清理多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        return text

    def truncate(self, text: str) -> str:
        if len(text) <= self.max_body_length:
            return text
        half = self.max_body_length // 2
        return text[:half] + "\n\n...(内容已截断)...\n\n" + text[-half:]

    def build_context(self, email_data: EmailData) -> str:
        cleaned = self.clean_text(email_data.body_text)
        truncated = self.truncate(cleaned)

        parts = [
            f"发件人: {email_data.sender_name} <{email_data.sender}>",
            f"主题: {email_data.subject}",
            f"日期: {email_data.date.strftime('%Y-%m-%d %H:%M')}",
        ]
        if email_data.has_attachments:
            parts.append(f"附件: {', '.join(email_data.attachment_names)}")
        parts.append(f"\n正文:\n{truncated}")

        return "\n".join(parts)

    def process(self, email_data: EmailData) -> EmailData:
        email_data.body_text = self.clean_text(email_data.body_text)
        return email_data
