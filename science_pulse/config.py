from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_DOMAINS = ["math", "physics", "cs"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "schedule": ["09:00", "13:00", "17:00", "21:00"],
    "timezone": "Europe/Moscow",
    "domains": DEFAULT_DOMAINS,
    "max_queue": 80,
    "low_water": 9,
    "harvest_per_source": 2,
    "translate": False,
    "doctor": {"posts_per_day": 4},
    "trending": {"enabled": True, "top": 5, "auto_enqueue_min_likes": 0},
    "abtest": {"enabled": False, "variants": ["classic", "compact"]},
    "edge": {"d1_primary": False},
    "site_base_url": "",
    "site_title": "Science Pulse",
    "data_dir": "data",
    "dist_dir": "dist",
    "card": {
        "size": 1080,
        "ssaa": 2,
        "theme": "neon",
    },
    "sources": {
        "history_canon": {"enabled": True, "weight": 50},
        "stackexchange": {
            "enabled": True,
            "weight": 10,
            "sites": {
                "math": [["math", "calculus"], ["math", "linear-algebra"]],
                "physics": [["physics", "quantum-mechanics"], ["physics", "classical-mechanics"]],
                "cs": [["cs", "algorithms"], ["cstheory", "complexity-theory"]],
            },
        },
        "oeis": {"enabled": True, "weight": 8},
        "wikipedia": {"enabled": True, "weight": 6},
        "arxiv": {"enabled": True, "weight": 5},
        "rosetta": {"enabled": True, "weight": 7},
        "github_raw": {
            "enabled": False,
            "weight": 5,
            "urls": [
                {
                    "url": "https://raw.githubusercontent.com/Experience-Monks/math-as-code/master/README.md",
                    "domain": "math",
                },
                {
                    "url": "https://raw.githubusercontent.com/brandonhimpfen/awesome-physics/master/README.md",
                    "domain": "physics",
                },
                {
                    "url": "https://raw.githubusercontent.com/TheAlgorithms/Python/master/README.md",
                    "domain": "cs",
                },
            ],
        },
        "numbers": {"enabled": True, "weight": 3},
        "offline": {"enabled": True, "weight": 100},
    },
    "platforms": {
        "telegram": {"enabled": True},
        "threads": {"enabled": True},
        "bluesky": {"enabled": True},
        "discord": {"enabled": True},
        "mastodon": {"enabled": True},
        "vk": {"enabled": True},
    },
    "telegram": {
        "channel_id": "",
        "admin_chat_id": "",
        "message_thread_id": "",
        "parse_mode": "HTML",
    },
    "threads": {"user_id": ""},
    "mastodon": {"instance": "https://mathstodon.xyz"},
    "vk": {"group_id": ""},
    "admin": {"enabled": True, "poll_timeout": 25},
    "source_circuit": {"failures": 3, "open_minutes": 45},
}


def _load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env без внешних зависимостей."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _deep_merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass
class Config:
    raw: Dict[str, Any] = field(default_factory=dict)
    root: Path = field(default_factory=lambda: Path.cwd())

    @property
    def data_dir(self) -> Path:
        return self.root / str(self.raw.get("data_dir", "data"))

    @property
    def dist_dir(self) -> Path:
        return self.root / str(self.raw.get("dist_dir", "dist"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "science.db"

    @property
    def cards_dir(self) -> Path:
        return self.data_dir / "cards"

    @property
    def schedule(self) -> List[str]:
        return list(self.raw.get("schedule") or DEFAULT_CONFIG["schedule"])

    @property
    def timezone(self) -> str:
        return str(self.raw.get("timezone", "Europe/Moscow"))

    @property
    def domains(self) -> List[str]:
        return list(self.raw.get("domains") or DEFAULT_DOMAINS)

    @property
    def max_queue(self) -> int:
        return int(self.raw.get("max_queue", 80))

    @property
    def low_water(self) -> int:
        """Порог очереди: ниже него пайплайн сам дозаказывает harvest."""
        return int(self.raw.get("low_water", 9))

    @property
    def translate(self) -> bool:
        return bool(self.raw.get("translate", False))

    @property
    def site_base_url(self) -> str:
        """Адрес сайта: config → .env → авто-определение из git remote (GitHub Pages)."""
        configured = str(self.raw.get("site_base_url") or "").strip()
        if configured:
            return configured.rstrip("/")
        env = os.getenv("SP_SITE_BASE_URL", "").strip()
        if env:
            return env.rstrip("/")
        return self.detect_site_url_from_git()

    def detect_site_url_from_git(self) -> str:
        """Определяет GitHub Pages из `git remote get-url origin` (кроме чужого `kern`)."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(self.root), capture_output=True, text=True, timeout=5, check=False,
            )
        except Exception:
            return ""
        if result.returncode != 0:
            return ""
        return parse_git_remote(result.stdout.strip())

    @property
    def site_title(self) -> str:
        return str(self.raw.get("site_title", "Science Pulse"))

    @property
    def miniapp_public(self) -> bool:
        """Публиковать ли Mini App «Пульт» (``dist/pult.html``) на сайте.

        По умолчанию ``False``: страница показывает операционное состояние
        (очередь, площадки, источники) и не должна быть доступна посторонним.
        Включайте осознанно: ``miniapp.public: true`` или ``SP_MINIAPP_PUBLIC=1``.
        """
        value = bool((self.raw.get("miniapp") or {}).get("public", False))
        return _env_bool("SP_MINIAPP_PUBLIC", value)

    @property
    def card(self) -> Dict[str, Any]:
        return dict(self.raw.get("card") or {})

    @property
    def sources(self) -> Dict[str, Any]:
        return dict(self.raw.get("sources") or {})

    @property
    def platforms(self) -> Dict[str, Any]:
        return dict(self.raw.get("platforms") or {})

    @property
    def telegram_channel(self) -> str:
        return os.getenv("TG_CHANNEL_ID") or str(
            (self.raw.get("telegram") or {}).get("channel_id", "")
        )

    @property
    def telegram_admin_chat(self) -> str:
        return os.getenv("TG_ADMIN_CHAT_ID") or str(
            (self.raw.get("telegram") or {}).get("admin_chat_id", "")
        )

    @property
    def telegram_thread_id(self) -> str:
        return os.getenv("TG_MESSAGE_THREAD_ID") or str(
            (self.raw.get("telegram") or {}).get("message_thread_id", "")
        )

    @property
    def telegram_token(self) -> str:
        return os.getenv("TG_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")

    @property
    def threads_user_id(self) -> str:
        return os.getenv("TH_USER_ID") or os.getenv("THREADS_USER_ID", "") or str(
            (self.raw.get("threads") or {}).get("user_id", "")
        )

    @property
    def threads_token(self) -> str:
        return os.getenv("TH_ACCESS_TOKEN") or os.getenv("THREADS_ACCESS_TOKEN", "")

    @property
    def mastodon_instance(self) -> str:
        return os.getenv("MASTODON_INSTANCE") or str(
            (self.raw.get("mastodon") or {}).get("instance", "https://mathstodon.xyz")
        )

    @property
    def vk_group_id(self) -> str:
        return os.getenv("VK_GROUP_ID") or str((self.raw.get("vk") or {}).get("group_id", ""))

    @property
    def cf_worker_url(self) -> str:
        return (os.getenv("CF_WORKER_URL") or "").rstrip("/")

    @property
    def ingest_secret(self) -> str:
        return os.getenv("INGEST_SECRET", "")

    @property
    def source_circuit(self) -> Dict[str, int]:
        return dict(self.raw.get("source_circuit") or {"failures": 3, "open_minutes": 45})

    def platform_enabled(self, name: str) -> bool:
        """Площадка включена? Неизвестные площадки выключены (безопасный дефолт)."""
        from .platforms_info import PLATFORMS

        if name not in PLATFORMS:
            return False
        return bool((self.platforms.get(name) or {}).get("enabled", True))

    def source_enabled(self, name: str) -> bool:
        return bool((self.sources.get(name) or {}).get("enabled", True))

    def source_options(self, name: str) -> Dict[str, Any]:
        return dict(self.sources.get(name) or {})

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)


def parse_git_remote(url: str) -> str:
    """git remote → адрес GitHub Pages.

    `git@github.com:owner/repo.git` и `https://github.com/owner/repo` дают
    `https://owner.github.io/repo`. Чужой проект `kern` намеренно игнорируется:
    Science Pulse никогда не публикуется в него.
    """
    import re

    match = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", str(url or "").strip())
    if not match:
        return ""
    owner, repo = match.group(1), match.group(2)
    if repo.strip().lower() == "kern":
        return ""
    return f"https://{owner}.github.io/{repo}"


def load_config(path: str | Path | None = None, root: str | Path | None = None) -> Config:
    base_root = Path(root) if root else Path.cwd()
    if path is None:
        path = base_root / "config.yaml"
    else:
        path = Path(path)

    _load_dotenv(base_root / ".env")

    data: Dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
            if isinstance(loaded, dict):
                data = loaded

    merged = _deep_merge(DEFAULT_CONFIG, data)

    if os.getenv("SP_DATA_DIR"):
        merged["data_dir"] = os.getenv("SP_DATA_DIR")
    if os.getenv("SP_DIST_DIR"):
        merged["dist_dir"] = os.getenv("SP_DIST_DIR")
    if os.getenv("SP_SCHEDULE"):
        merged["schedule"] = [
            item.strip() for item in os.getenv("SP_SCHEDULE", "").split(",") if item.strip()
        ]
    if os.getenv("SP_SITE_BASE_URL"):
        merged["site_base_url"] = os.getenv("SP_SITE_BASE_URL")
    if os.getenv("SP_SITE_TITLE"):
        merged["site_title"] = os.getenv("SP_SITE_TITLE")
    if os.getenv("STACKEXCHANGE_API_KEY"):
        merged["stackexchange_key"] = os.getenv("STACKEXCHANGE_API_KEY")
    merged["translate"] = _env_bool("SP_TRANSLATE", bool(merged.get("translate", False)))

    if not merged.get("telegram"):
        merged["telegram"] = {}
    if os.getenv("TG_CHANNEL_ID"):
        merged["telegram"]["channel_id"] = os.getenv("TG_CHANNEL_ID")
    if os.getenv("TG_ADMIN_CHAT_ID"):
        merged["telegram"]["admin_chat_id"] = os.getenv("TG_ADMIN_CHAT_ID")
    if os.getenv("TG_MESSAGE_THREAD_ID"):
        merged["telegram"]["message_thread_id"] = os.getenv("TG_MESSAGE_THREAD_ID")

    if not merged.get("threads"):
        merged["threads"] = {}
    if os.getenv("TH_USER_ID"):
        merged["threads"]["user_id"] = os.getenv("TH_USER_ID")

    if not merged.get("mastodon"):
        merged["mastodon"] = {}
    if os.getenv("MASTODON_INSTANCE"):
        merged["mastodon"]["instance"] = os.getenv("MASTODON_INSTANCE")

    if not merged.get("vk"):
        merged["vk"] = {}
    if os.getenv("VK_GROUP_ID"):
        merged["vk"]["group_id"] = os.getenv("VK_GROUP_ID")

    config = Config(raw=merged, root=base_root)
    config.ensure_dirs()
    return config
