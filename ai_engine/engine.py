import json
import time
from pathlib import Path

from loguru import logger

from src.models import ActionItem, ClassificationResult, EmailData, ProcessResult, ReplyDecision, ReplyDraft
from src.preprocessor import EmailPreprocessor

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
except ImportError:
    HumanMessage = None
    SystemMessage = None
    ChatOpenAI = None


class AIEngine:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini",
                 base_url: str | None = None,
                 max_tokens: int = 500, temperature: float = 0.1,
                 retry_count: int = 3, retry_delay: int = 1,
                 max_body_length: int = 2000, categories: list[str] | None = None):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.preprocessor = EmailPreprocessor(max_body_length)
        self.categories = categories or [
            "工作", "财务", "订阅通知", "社交", "促销广告", "重要紧急", "垃圾邮件", "其他"
        ]
        self._prompts = self._load_prompts()
        self._llm = None

    def _load_prompts(self) -> dict[str, str]:
        prompts = {}
        prompt_dir = Path(__file__).parent.parent / "prompts"
        for name in ["classify", "summarize", "extract_actions"]:
            path = prompt_dir / f"{name}.txt"
            if path.exists():
                prompts[name] = path.read_text(encoding="utf-8")
        return prompts

    def _call_api(self, messages: list[dict]) -> str:
        for attempt in range(self.retry_count):
            try:
                response = self._get_llm().invoke(self._to_langchain_messages(messages))
                return self._normalize_response_content(response.content)
            except Exception as e:
                logger.warning(f"LangChain 调用失败 (尝试 {attempt + 1}/{self.retry_count}): {e}")
                if attempt < self.retry_count - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    raise

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        if ChatOpenAI is None:
            raise RuntimeError(
                "缺少 LangChain 依赖，请先运行：pip install -r requirements.txt"
            )

        kwargs = {
            "model": self.model,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url

        self._llm = ChatOpenAI(**kwargs)
        return self._llm

    def _to_langchain_messages(self, messages: list[dict]):
        if HumanMessage is None or SystemMessage is None:
            raise RuntimeError(
                "缺少 LangChain 依赖，请先运行：pip install -r requirements.txt"
            )

        converted = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                converted.append(SystemMessage(content=content))
            else:
                converted.append(HumanMessage(content=content))
        return converted

    @staticmethod
    def _normalize_response_content(content) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content).strip()

    def classify(self, email_data: EmailData) -> ClassificationResult:
        context = self.preprocessor.build_context(email_data)
        categories_str = "、".join(self.categories)

        system_prompt = self._prompts.get("classify",
            "你是一个邮件分类助手。请将邮件分类到最合适的类别中，并返回 JSON 格式结果。")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"可选分类：{categories_str}\n\n{context}\n\n"
                                        f'请返回 JSON：{{"category": "分类名", "confidence": 0.95, "reason": "简短理由"}}'}
        ]

        result = self._call_api(messages)
        data = self._parse_json(result)
        return ClassificationResult(
            category=data.get("category", "其他"),
            confidence=float(data.get("confidence", 0.5)),
            reason=data.get("reason", ""),
        )

    def summarize(self, email_data: EmailData) -> str:
        context = self.preprocessor.build_context(email_data)

        system_prompt = self._prompts.get("summarize",
            "请用 2-3 句中文概括邮件的核心内容，突出关键信息和行动项。")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ]

        return self._call_api(messages)

    def extract_actions(self, email_data: EmailData) -> list[ActionItem]:
        context = self.preprocessor.build_context(email_data)

        system_prompt = self._prompts.get("extract_actions",
            "请从邮件中提取需要采取的行动项，返回 JSON 数组。")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context + '\n\n请返回 JSON 数组：[{"action": "行动描述", "deadline": "截止日期或空", "priority": "high/normal/low"}]\n如果没有行动项，返回空数组 []'}
        ]

        result = self._call_api(messages)
        items = self._parse_json(result)
        if not isinstance(items, list):
            return []
        return [ActionItem(
            action=item.get("action", ""),
            deadline=item.get("deadline", ""),
            priority=item.get("priority", "normal"),
        ) for item in items]

    def process_email(self, email_data: EmailData) -> ProcessResult:
        logger.info(f"AI 处理邮件: {email_data.subject[:50]}")
        classification = self.classify(email_data)
        summary = self.summarize(email_data)
        actions = self.extract_actions(email_data)
        return ProcessResult(
            classification=classification,
            summary=summary,
            action_items=actions,
        )

    def process_batch(self, emails: list[EmailData]) -> list[tuple[EmailData, ProcessResult]]:
        results = []
        for i, email_data in enumerate(emails):
            logger.info(f"处理进度: {i + 1}/{len(emails)}")
            try:
                result = self.process_email(email_data)
                results.append((email_data, result))
            except Exception as e:
                logger.error(f"处理邮件失败 [{email_data.subject}]: {e}")
        return results

    def decide_reply(self, email_data: EmailData, result: ProcessResult) -> ReplyDecision:
        context = self.preprocessor.build_context(email_data)
        prompt = (
            "你是邮件处理系统的回复路由器。判断这封邮件是否需要人工审核后的正式回复。\n"
            "需要回复的例子：客户咨询、招聘沟通、需要确认的信息、对方提出问题或请求。\n"
            "不需要回复的例子：垃圾邮件、促销广告、纯通知、系统自动邮件、无需行动的订阅消息。\n"
            "只返回 JSON：{\"needs_reply\": true/false, \"reason\": \"简短原因\"}。"
        )
        user_prompt = (
            f"{context}\n\n"
            f"分类：{result.classification.category}\n"
            f"摘要：{result.summary}\n"
            f"待办数：{len(result.action_items)}"
        )
        data = self._parse_json(self._call_api([
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_prompt},
        ]))
        if not isinstance(data, dict):
            data = {}
        return ReplyDecision(
            needs_reply=_to_bool(data.get("needs_reply")),
            reason=str(data.get("reason") or ""),
        )

    def draft_reply(self, email_data: EmailData, result: ProcessResult) -> ReplyDraft:
        context = self.preprocessor.build_context(email_data)
        prompt = (
            "你是专业邮件助理。请基于原始邮件写一封可发送的中文回复草稿。\n"
            "要求：礼貌、简洁、具体；不要编造原邮件没有的信息；不要包含占位符；"
            "如果需要人工补充信息，用自然语言说明需要补充的内容。\n"
            "只返回 JSON：{\"subject\": \"回复主题\", \"body\": \"邮件正文\"}。"
        )
        user_prompt = (
            f"{context}\n\n"
            f"分类：{result.classification.category}\n"
            f"摘要：{result.summary}\n"
            f"待办：{'; '.join(item.action for item in result.action_items) or '无'}"
        )
        data = self._parse_json(self._call_api([
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_prompt},
        ]))
        if not isinstance(data, dict):
            data = {}
        return ReplyDraft(
            subject=str(data.get("subject") or _reply_subject(email_data.subject)),
            body=str(data.get("body") or ""),
        )

    def revise_reply(
        self,
        email_record: dict,
        current_subject: str,
        current_body: str,
        reviewer_notes: str,
    ) -> ReplyDraft:
        prompt = (
            "你是邮件回复润色助理。请根据人工修改意见，结合原始邮件和当前回复草稿，"
            "重写一版可发送的回复。不要编造原邮件没有的信息。"
            "只返回 JSON：{\"subject\": \"回复主题\", \"body\": \"邮件正文\"}。"
        )
        user_prompt = (
            f"原始邮件：\n{_record_context(email_record)}\n\n"
            f"当前回复主题：{current_subject}\n\n"
            f"当前回复正文：\n{current_body}\n\n"
            f"人工修改意见：\n{reviewer_notes}"
        )
        data = self._parse_json(self._call_api([
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_prompt},
        ]))
        if not isinstance(data, dict):
            data = {}
        return ReplyDraft(
            subject=str(data.get("subject") or current_subject or _reply_subject(email_record.get("subject", ""))),
            body=str(data.get("body") or current_body or ""),
        )

    def generate_daily_report(self, emails: list[dict], start_at: str, end_at: str) -> str:
        if not emails:
            return f"邮件日报（{start_at} ~ {end_at}）\n\n该时间段内没有已处理邮件。"

        lines = []
        for index, email_data in enumerate(emails, start=1):
            actions = email_data.get("action_preview") or ""
            action_text = f"\n待办：{actions}" if actions else ""
            lines.append(
                f"{index}. [{email_data.get('category', '未分类')}] "
                f"{email_data.get('subject', '(无主题)')}\n"
                f"发件人：{email_data.get('sender_name') or email_data.get('sender') or '未知'}\n"
                f"时间：{email_data.get('date', '')}\n"
                f"摘要：{email_data.get('summary', '')}"
                f"{action_text}"
            )

        system_prompt = (
            "你是一个邮件日报助手。请根据给定邮件处理结果生成中文日报。"
            "要求：先给总体概览，再按重要事项、待办事项、普通通知、可忽略信息分组；"
            "最后给出明天需要优先跟进的事项。内容要具体、可执行，不要编造邮件中没有的信息。"
        )
        user_prompt = (
            f"统计时间范围：{start_at} 到 {end_at}\n"
            f"邮件数量：{len(emails)}\n\n"
            "邮件列表：\n" + "\n\n".join(lines)
        )
        return self._call_api([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])

    def _parse_json(self, text: str):
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            for index, char in enumerate(text):
                if char in "{[":
                    try:
                        return json.loads(text[index:])
                    except json.JSONDecodeError:
                        continue
            logger.warning(f"无法解析 JSON: {text[:200]}")
            return {} if "{" in text else []


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"true", "yes", "1", "需要", "是"}


def _reply_subject(subject: str) -> str:
    subject = subject or "(无主题)"
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


def _record_context(email_record: dict) -> str:
    parts = [
        f"发件人：{email_record.get('sender_name') or email_record.get('sender') or ''} <{email_record.get('sender') or ''}>",
        f"收件人：{email_record.get('recipient') or ''}",
        f"主题：{email_record.get('subject') or ''}",
        f"时间：{email_record.get('date') or ''}",
        f"摘要：{email_record.get('summary') or ''}",
        f"正文：\n{email_record.get('raw_body_text') or email_record.get('body_text') or ''}",
    ]
    return "\n".join(parts)
