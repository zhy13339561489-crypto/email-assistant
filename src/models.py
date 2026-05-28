from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EmailData:
    uid: str
    subject: str
    sender: str
    sender_name: str
    to: str
    date: datetime
    body_text: str
    has_attachments: bool = False
    attachment_names: list[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    reason: str


@dataclass
class ActionItem:
    action: str
    deadline: str = ""
    priority: str = "normal"


@dataclass
class ProcessResult:
    classification: ClassificationResult
    summary: str
    action_items: list[ActionItem] = field(default_factory=list)
