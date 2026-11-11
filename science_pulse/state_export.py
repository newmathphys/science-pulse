from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import requests

from .config import Config
from .storage import SCHEMA, Storage

LOGGER = logging.getLogger(__name__)


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _chunks(items: List[Dict[str, Any]], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def to_sql(snapshot: Dict[str, List[Dict[str, Any]]]) -> str:
    """SQL-дамп снимка состояния (схема + INSERT OR REPLACE) для D1."""
    lines = [SCHEMA.strip(), ""]
    for table, rows in snapshot.items():
        for row in rows:
            if not row:
                continue
            columns = list(row.keys())
            values = ", ".join(_sql_literal(row[column]) for column in columns)
            lines.append(f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({values});")
    return "\n".join(lines) + "\n"


class StateSync:
    """D1-Primary состояние через Cloudflare Worker (`/api/state`).

    D1 — источник истины для CI; локальный SQLite — рабочая копия/кэш.
    Запись защищена lease-lock, чтобы два раннера не публиковали одновременно.
    HTTP инъектируется — тесты идут без сети.
    """

    def __init__(
        self,
        config: Config,
        storage: Storage,
        http_post: Optional[Callable[..., Any]] = None,
        http_get: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self.storage = storage
        self._post = http_post or requests.post
        self._get = http_get or requests.get

    def available(self) -> bool:
        return bool(self.config.cf_worker_url and self.config.ingest_secret)

    def endpoint(self) -> str:
        return f"{self.config.cf_worker_url}/api/state"

    def acquire_lock(self, owner: str, ttl_s: int = 900) -> Dict[str, Any]:
        """Захватывает lease-lock D1. Возвращает ok=False, если lock занят.

        На время rollout старый Worker может ещё не знать `/lock`: 404/405
        считаются «degraded» и не блокируют конвейер, если lock_required=false.
        """
        if not self.available():
            return {"ok": False, "error": "CF_WORKER_URL/INGEST_SECRET не заданы"}
        if not str(owner or "").strip():
            return {"ok": False, "error": "пустой owner lock"}
        headers = {"Authorization": f"Bearer {self.config.ingest_secret}"}
        try:
            response = self._post(
                f"{self.endpoint()}/lock",
                headers=headers,
                json={"owner": str(owner)[:200], "ttl_s": max(30, int(ttl_s))},
                timeout=30,
            )
            payload = response.json() if hasattr(response, "json") else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception as exc:
            return {"ok": False, "error": f"lock: {str(exc)[:200]}"}
        status = getattr(response, "status_code", 0)
        required = bool((self.config.raw.get("edge") or {}).get("lock_required", False))
        if status in (404, 405) or (
            status in (200, 201, 204) and not payload.get("ok") and not payload.get("locked")
        ):
            if not required:
                return {
                    "ok": True,
                    "degraded": "lock endpoint not deployed; single-writer disabled",
                    "error": "",
                }
        if status not in (200, 201, 204):
            return {
                "ok": False,
                "locked": bool(payload.get("locked")),
                "owner": str(payload.get("owner") or ""),
                "expires_at": payload.get("expires_at"),
                "error": str(payload.get("error") or f"lock HTTP {status}"),
            }
        return {
            "ok": bool(payload.get("ok")),
            "locked": bool(payload.get("locked")),
            "owner": str(payload.get("owner") or ""),
            "expires_at": payload.get("expires_at"),
            "error": str(payload.get("error") or ""),
        }

    def release_lock(self, owner: str) -> Dict[str, Any]:
        """Освобождает lease-lock, только если owner совпадает."""
        if not self.available():
            return {"ok": False, "error": "CF_WORKER_URL/INGEST_SECRET не заданы"}
        headers = {"Authorization": f"Bearer {self.config.ingest_secret}"}
        try:
            response = self._post(
                f"{self.endpoint()}/unlock",
                headers=headers,
                json={"owner": str(owner)[:200]},
                timeout=30,
            )
            payload = response.json() if hasattr(response, "json") else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception as exc:
            return {"ok": False, "error": f"unlock: {str(exc)[:200]}"}
        return {
            "ok": bool(payload.get("ok")) and getattr(response, "status_code", 0) in (200, 201, 204),
            "released": bool(payload.get("released")),
            "error": str(payload.get("error") or ""),
        }

    def counts(self) -> Dict[str, int]:
        return {table: len(rows) for table, rows in self.storage.snapshot().items()}

    def export_sql(self) -> str:
        return to_sql(self.storage.snapshot())

    def push(self, batch_size: int = 200) -> Dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "CF_WORKER_URL/INGEST_SECRET не заданы", "rows": 0, "batches": 0}
        snapshot = self.storage.snapshot()
        headers = {"Authorization": f"Bearer {self.config.ingest_secret}"}
        endpoint = self.endpoint()
        size = max(1, int(batch_size))
        rows = 0
        failed = 0
        batches = 0
        for table, items in snapshot.items():
            for chunk in _chunks(items, size):
                if not chunk:
                    continue
                batches += 1
                try:
                    response = self._post(endpoint, headers=headers, json={"tables": {table: chunk}}, timeout=60)
                    if getattr(response, "status_code", 0) in (200, 201, 204):
                        rows += len(chunk)
                    else:
                        failed += len(chunk)
                except Exception as exc:
                    LOGGER.warning("State push %s: %s", table, exc)
                    failed += len(chunk)
        return {"ok": failed == 0, "rows": rows, "failed": failed, "batches": batches, "endpoint": endpoint}

    def pull(self) -> Dict[str, Any]:
        """Скачивает полный снимок D1 и монотонно сливает его в локальный SQLite."""
        if not self.available():
            return {"ok": False, "error": "CF_WORKER_URL/INGEST_SECRET не заданы", "merged": {}}
        try:
            response = self._get(
                f"{self.endpoint()}?full=1",
                headers={"Authorization": f"Bearer {self.config.ingest_secret}"},
                timeout=60,
            )
            payload = response.json()
        except Exception as exc:
            LOGGER.warning("State pull: %s", exc)
            return {"ok": False, "error": str(exc)[:200], "merged": {}}
        if not payload.get("ok", True):
            return {"ok": False, "error": str(payload)[:200], "merged": {}}
        merged = self.storage.merge_snapshot(payload.get("tables") or {})
        return {"ok": True, "merged": merged, "endpoint": self.endpoint()}

    def sync(self, batch_size: int = 200) -> Dict[str, Any]:
        """Pull → Push: забрать свежий стейт из D1, затем отправить локальный."""
        pull_result = self.pull()
        push_result = self.push(batch_size=batch_size)
        return {
            "ok": bool(pull_result.get("ok") and push_result.get("ok")),
            "pull": pull_result,
            "push": push_result,
        }
