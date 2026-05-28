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
    raw_body_text: str = ""
    raw_headers: str = ""
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


@dataclass
class ReplyDecision:
    needs_reply: bool
    reason: str = ""


@dataclass
class ReplyDraft:
    subject: str
    body: str
    reviewer_notes: str = ""
    review_rounds: int = 0
    review_passed: bool = False


@dataclass
class ReplyReview:
    approved: bool
    comments: str = ""
    reason: str = ""
