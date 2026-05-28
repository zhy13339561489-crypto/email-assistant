import json
import time
from pathlib import Path

from loguru import logger

from src.models import ActionItem, ClassificationResult, EmailData, ProcessResult
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
