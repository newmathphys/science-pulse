"""Реестр сгенерированных видео: что, когда и каким движком собрано."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STATE_NAME = "video_registry.json"


def _path(config: Any, path: Optional[Path] = None) -> Path:
    return Path(path) if path else config.data_dir / STATE_NAME


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def register_video(config: Any, post: Any, style: str, aspect: str, path: str | Path,
                   engine: str = "", extra: Optional[Dict[str, Any]] = None,
                   state_path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path)
    target_path = _path(config, state_path)
    data = _read(target_path)
    digest = ""
    size = 0
    if target.is_file():
        size = target.stat().st_size
        digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
    key = f"{getattr(post, 'id', '')}:{style}:{aspect}"
    try:
        display_path = str(target.relative_to(config.root))
    except ValueError:
        display_path = str(target)
    entry = {
        "key": key,
        "post_id": getattr(post, "id", ""),
        "title": getattr(post, "title", ""),
        "style": style,
        "aspect": aspect,
        "path": display_path,
        "engine": engine,
        "bytes": size,
        "sha256_16": digest,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        **(extra or {}),
    }
    data[key] = entry
    _write(target_path, data)
    return entry


def list_videos(config: Any, state_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    data = _read(_path(config, state_path))
    return sorted(data.values(), key=lambda item: str(item.get("created_at", "")), reverse=True)


def format_registry(config: Any, state_path: Optional[Path] = None) -> str:
    items = list_videos(config, state_path)
    lines = [f"🎬 Реестр видео · {len(items)}", ""]
    for item in items:
        size = int(item.get("bytes") or 0) // 1024
        lines.append(
            f"• <b>{item.get('title', '')}</b> · {item.get('style')} · {item.get('aspect')} · "
            f"{size} КБ · {item.get('engine') or '—'}"
        )
        lines.append(f"  <code>{item.get('path', '')}</code>")
    return "\n".join(lines)
