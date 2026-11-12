"""Wikidata SPARQL-мост: русский термин, определение и формула P2534.

Детерминированный источник без LLM. Ответы кэшируются в JSON, поэтому
повторные прогоны и unittest не ходят в сеть. Для query.wikidata.org
обязателен явный User-Agent с контактом проекта.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

LOGGER = logging.getLogger(__name__)

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "SciencePulse/1.0 (https://newmathphys.com)"


class WikidataClient:
    def __init__(
        self,
        cache_path: str | Path | None = None,
        http_get: Optional[Callable[..., Any]] = None,
    ):
        self.cache_path = Path(cache_path) if cache_path else Path("data/wikidata_cache.json")
        self._get = http_get or requests.get
        self._cache: Dict[str, Dict[str, str]] = self._read_cache()

    def _read_cache(self) -> Dict[str, Dict[str, str]]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            LOGGER.warning("wikidata cache: %s", exc)

    @staticmethod
    def _query(term: str) -> str:
        safe = str(term or "").replace("\\", "\\\\").replace('"', '\\"')
        return (
            "SELECT ?item ?itemLabel ?itemDescription ?formula WHERE { "
            f'?item rdfs:label "{safe}"@en. '
            "OPTIONAL { ?item wdt:P2534 ?formula. } "
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". } '
            "} LIMIT 1"
        )

    @staticmethod
    def _parse(payload: Dict[str, Any]) -> Dict[str, str]:
        bindings = (((payload or {}).get("results") or {}).get("bindings") or [])
        if not bindings:
            return {}
        row = bindings[0] or {}
        item = str((row.get("item") or {}).get("value") or "")
        qid = item.rsplit("/", 1)[-1] if item else ""
        return {
            "qid": qid,
            "term": str((row.get("itemLabel") or {}).get("value") or ""),
            "description": str((row.get("itemDescription") or {}).get("value") or ""),
            "formula": str((row.get("formula") or {}).get("value") or ""),
        }

    def lookup_cached(self, term: str) -> Dict[str, str]:
        return dict(self._cache.get(str(term or "").strip().lower(), {}))

    def lookup(self, term: str, use_cache: bool = True) -> Dict[str, str]:
        key = str(term or "").strip().lower()
        if not key:
            return {}
        if use_cache and key in self._cache:
            return dict(self._cache[key])
        try:
            response = self._get(
                ENDPOINT,
                params={"query": self._query(term), "format": "json"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=30,
            )
            payload = response.json() if hasattr(response, "json") else {}
        except Exception as exc:
            LOGGER.warning("wikidata %s: %s", term, exc)
            return {}
        data = self._parse(payload if isinstance(payload, dict) else {})
        if data:
            self._cache[key] = data
            self._write_cache()
        return data
