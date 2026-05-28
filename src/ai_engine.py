import json
import time
from pathlib import Path

from openai import OpenAI
from loguru import logger

from .models import EmailData, ClassificationResult, ActionItem, ProcessResult
from .preprocessor import EmailPreprocessor


class AIEngine:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini",
                 base_url: str | None = None,
                 max_tokens: int = 500, temperature: float = 0.1,
                 retry_count: int = 3, retry_delay: int = 1,
                 max_body_length: int = 2000, categories: list[str] | None = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
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
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"API 调用失败 (尝试 {attempt + 1}/{self.retry_count}): {e}")
                if attempt < self.retry_count - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    raise

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

    def _parse_json(self, text: str):
        # 尝试从可能包含 markdown 代码块的响应中提取 JSON
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到第一个 { 或 [
            for i, ch in enumerate(text):
                if ch in "{[":
                    try:
                        return json.loads(text[i:])
                    except json.JSONDecodeError:
                        continue
            logger.warning(f"无法解析 JSON: {text[:200]}")
            return {} if "{" in text else []
