from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Type

from ..config import Config
from ..models import Post
from ..storage import Storage
from .arxiv import ArxivSource
from .base import HttpClient, Source, SourceError
from .foundation import FoundationSource
from .github_raw import GitHubRawSource
from .history_canon import HistoryCanonSource
from .numbers import NumbersSource
from .oeis import OEISSource
from .offline import OfflineBunkerSource
from .rosetta import RosettaSource
from .stackexchange import StackExchangeSource
from .wikipedia import WikipediaSource

LOGGER = logging.getLogger(__name__)

REGISTRY: Dict[str, Type[Source]] = {
    "foundation": FoundationSource,
    "history_canon": HistoryCanonSource,
    "stackexchange": StackExchangeSource,
    "oeis": OEISSource,
    "wikipedia": WikipediaSource,
    "arxiv": ArxivSource,
    "rosetta": RosettaSource,
    "github_raw": GitHubRawSource,
    "numbers": NumbersSource,
    "offline": OfflineBunkerSource,
}


class SourceManager:
    def __init__(self, config: Config, storage: Storage, http: Optional[HttpClient] = None):
        self.config = config
        self.storage = storage
        self.http = http or HttpClient()
        self.sources: Dict[str, Source] = {}
        for name, cls in REGISTRY.items():
            if not config.source_enabled(name):
                continue
            try:
                self.sources[name] = cls(config, self.http)
            except Exception as exc:  # pragma: no cover - защита от битой зависимости
                LOGGER.warning("Источник %s не инициализирован: %s", name, exc)

    def ordered_names(self) -> List[str]:
        def key(name: str) -> tuple[int, int]:
            weight = int((self.config.source_options(name).get("weight") or 0))
            return (1 if name == "offline" else 0, -weight)

        return sorted(self.sources.keys(), key=key)

    def fetch(
        self,
        limit_per_source: int = 2,
        domains: Optional[Iterable[str]] = None,
        include_offline: bool = True,
    ) -> List[Post]:
        allowed = set(domains or self.config.domains)
        posts: List[Post] = []
        circuit = self.config.source_circuit
        all_domains = list(self.config.domains) or ["math", "physics", "cs"]
        cursor = self.storage.kv_int("harvest_cursor", 0)

        for source_index, name in enumerate(self.ordered_names()):
            if name == "offline" and not include_offline:
                continue
            if name != "offline" and self.storage.source_is_open(name):
                LOGGER.info("Источник %s в состоянии OPEN, пропуск", name)
                continue

            source = self.sources[name]
            if allowed and not (set(source.domains) & allowed):
                continue
            base_cycle = self.storage.kv_int(f"cycle:{name}", 0)
            if name in ("history_canon", "foundation"):
                cycle = base_cycle
            elif len(allowed) == 1:
                target_domain = next(iter(allowed))
                target_index = all_domains.index(target_domain) if target_domain in all_domains else 0
                cycle = base_cycle + ((target_index - base_cycle) % len(all_domains))
            else:
                cycle = base_cycle + cursor + source_index
            try:
                fetched = source.fetch(limit=limit_per_source, cycle=cycle)
            except Exception as exc:
                error = str(exc)
                LOGGER.warning("Источник %s упал: %s", name, error)
                self.storage.record_source_failure(
                    name,
                    error,
                    failures_limit=int(circuit.get("failures", 3)),
                    open_minutes=int(circuit.get("open_minutes", 45)),
                )
                continue

            self.storage.record_source_ok(name)
            if name in ("history_canon", "foundation"):
                self.storage.kv_set(f"cycle:{name}", base_cycle + max(1, len(fetched)))
            else:
                self.storage.bump_counter(f"cycle:{name}")
            for post in fetched:
                if post.domain not in allowed:
                    continue
                errors = post.validate()
                if errors:
                    LOGGER.info("Пост %s отклонён: %s", post.id, "; ".join(errors))
                    continue
                posts.append(post)

        self.storage.bump_counter("harvest_cursor")
        return posts

    def fetch_for_domain(self, domain: str, limit_per_source: int = 2) -> List[Post]:
        return self.fetch(limit_per_source=limit_per_source, domains=[domain])

    def status(self) -> List[Dict[str, object]]:
        result: List[Dict[str, object]] = []
        for name in self.ordered_names():
            state = self.storage.source_state(name)
            result.append(
                {
                    "name": name,
                    "enabled": True,
                    "open": self.storage.source_is_open(name),
                    "failures": state.get("failures", 0),
                    "last_ok": state.get("last_ok"),
                    "last_error": state.get("last_error"),
                    "tier": self.sources[name].tier,
                }
            )
        return result

    def close(self) -> None:
        self.http.close()
