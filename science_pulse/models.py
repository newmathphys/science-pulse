from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DOMAINS = ("math", "physics", "cs")

DOMAIN_LABELS = {
    "math": "МАТЕМАТИКА",
    "physics": "ФИЗИКА",
    "cs": "ИНФОРМАТИКА",
}

DOMAIN_EMOJI = {"math": "📐", "physics": "⚛️", "cs": "💻"}

DOMAIN_HASHTAGS = {
    "math": "#математика #math",
    "physics": "#физика #physics",
    "cs": "#информатика #программирование #cs",
}

PLATFORM_LIMITS = {
    "telegram_caption": 1024,
    "telegram_message": 4096,
    "threads": 500,
    "bluesky": 300,
    "discord": 2000,
    "discord_embed": 4096,
    "mastodon": 500,
    "vk": 16384,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_id(source: str, external: str | int) -> str:
    raw = f"{source}:{external}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _clean_line(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", " ").strip()
    return re.sub(r"[ \t]+", " ", text)


@dataclass
class Post:
    id: str
    domain: str
    title: str
    hook: str = ""
    body: str = ""
    formula_latex: str = ""
    formula_plain: str = ""
    code: str = ""
    source_name: str = ""
    source_url: str = ""
    tier: str = "online"
    quality: float = 0.5
    created_at: str = field(default_factory=utc_now)
    published_at: str = ""
    status: str = "ready"
    card_path: str = ""
    card_file_id: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.domain = self.domain if self.domain in DOMAINS else "math"
        self.title = _clean_line(self.title)
        self.hook = _clean_line(self.hook)
        self.body = (self.body or "").strip()
        self.formula_latex = (self.formula_latex or "").strip()
        self.formula_plain = (self.formula_plain or "").strip()
        self.code = (self.code or "").strip()
        if not self.formula_plain and self.formula_latex:
            self.formula_plain = self.formula_latex

    @property
    def label(self) -> str:
        return DOMAIN_LABELS.get(self.domain, self.domain.upper())

    @property
    def emoji(self) -> str:
        return DOMAIN_EMOJI.get(self.domain, "🔬")

    @property
    def hashtags(self) -> str:
        return DOMAIN_HASHTAGS.get(self.domain, "#наука #science")

    @property
    def has_math(self) -> bool:
        return bool(self.formula_latex or self.formula_plain)

    @property
    def plain_title(self) -> str:
        from .text import formula_to_unicode

        return formula_to_unicode(self.title, 240)

    @property
    def plain_hook(self) -> str:
        from .text import formula_to_unicode

        return formula_to_unicode(self.hook, 240)

    @property
    def short_body(self) -> str:
        text = re.sub(r"\s+", " ", self.body or self.hook or "").strip()
        return text[:420]

    def validate(self) -> List[str]:
        errors: List[str] = []
        if len(self.title) < 8:
            errors.append("слишком короткий заголовок")
        if len(self.title) > 240:
            errors.append("слишком длинный заголовок")
        if not self.body and not self.hook:
            errors.append("нет текста")
        if len(self.body) + len(self.hook) < 60:
            errors.append("текст короче 60 символов")
        if not self.has_math and not self.code and len(self.body) < 120:
            errors.append("нет формулы/кода и текст короче 120 символов")
        if self.source_url and not self.source_url.startswith(("http://", "https://")):
            errors.append("некорректный source_url")
        return errors

    def quality_score(self) -> float:
        score = 0.35
        if self.has_math:
            score += 0.25
        if self.code:
            score += 0.15
        if len(self.body) >= 220:
            score += 0.1
        if self.source_url:
            score += 0.05
        if self.tier == "online":
            score += 0.05
        if self.tier == "offline":
            score -= 0.05
        return round(max(0.0, min(1.0, score)), 3)

    def fingerprint(self) -> str:
        from .text import fingerprint

        return fingerprint(self)

    def to_row(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "domain": self.domain,
            "title": self.title,
            "hook": self.hook,
            "body": self.body,
            "formula_latex": self.formula_latex,
            "formula_plain": self.formula_plain,
            "code": self.code,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "tier": self.tier,
            "quality": self.quality,
            "created_at": self.created_at,
            "meta_json": json.dumps(self.meta, ensure_ascii=False),
        }

    @classmethod
    def from_row(cls, row: Any) -> "Post":
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except (TypeError, ValueError):
            meta = {}
        return cls(
            id=row["id"],
            domain=row["domain"],
            title=row["title"],
            hook=row["hook"] or "",
            body=row["body"] or "",
            formula_latex=row["formula_latex"] or "",
            formula_plain=row["formula_plain"] or "",
            code=row["code"] or "",
            source_name=row["source_name"] or "",
            source_url=row["source_url"] or "",
            tier=row["tier"] or "online",
            quality=float(row["quality"] or 0.5),
            created_at=row["created_at"],
            published_at=row["published_at"] or "",
            status=row["status"] or "ready",
            card_path=row["card_path"] or "",
            card_file_id=row["card_file_id"] or "",
            meta=meta,
        )


@dataclass
class CardArtifact:
    path: str
    data: bytes
    width: int
    height: int


@dataclass
class PublishResult:
    platform: str
    ok: bool
    skipped: bool = False
    external_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "ok": self.ok,
            "skipped": self.skipped,
            "external_id": self.external_id,
            "url": self.url,
            "error": self.error,
            "meta": self.meta,
        }
