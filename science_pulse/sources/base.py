from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from ..config import Config
from ..models import Post
from ..text import clean_text, translate_preserving_latex

USER_AGENT = "SciencePulseBot/0.1 (+https://github.com/science-pulse; educational content)"


class SourceError(RuntimeError):
    pass


class HttpClient:
    """Тонкая обёртка над requests: таймауты, лимит размера, User-Agent."""

    def __init__(self, timeout: float = 8.0, max_bytes: int = 2_000_000):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = self.session.get(url, **kwargs)
        except requests.RequestException as exc:
            raise SourceError(f"network error: {exc}") from exc
        if response.status_code >= 400:
            raise SourceError(f"HTTP {response.status_code} for {url}")
        if len(response.content) > self.max_bytes:
            raise SourceError(f"response too large: {len(response.content)} bytes")
        return response

    def get_json(self, url: str, **kwargs: Any) -> Any:
        response = self.get(url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(f"invalid JSON from {url}: {exc}") from exc

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.get(url, **kwargs).text

    def close(self) -> None:
        self.session.close()


class Source(ABC):
    name: str = "base"
    domains: tuple[str, ...] = ("math", "physics", "cs")
    tier: str = "online"

    def __init__(self, config: Config, http: Optional[HttpClient] = None):
        self.config = config
        self.http = http or HttpClient()

    def _translate(self, text: str) -> str:
        if not self.config.translate or not text:
            return text
        return translate_preserving_latex(text)

    def _clean(self, text: str, limit: int = 900) -> str:
        return clean_text(text, max_len=limit)

    @abstractmethod
    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        raise NotImplementedError

    def available(self) -> bool:
        return True
