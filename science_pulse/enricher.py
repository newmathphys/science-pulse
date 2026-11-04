"""Обогатитель лонгридов: структурный разбор из пяти разделов.

`enrich_post_longread(post, http_get=None, timeout=3.0)` собирает
1500–3000-символьный лонгрид:

1. **Исторический контекст и постановка задачи** — `era`, `scientist`, `hook`,
   полный `body` + выжимка из Википедии (если доступна);
2. **Аналитическая модель и экспликация величин** — `formula_plain`,
   `formula_vars` / `constants_used`;
3. **Вычислительная верификация** — `computed_example` и песочница кода из
   `post_proof.py` + merkle-печать;
4. **Связи в дереве фундамента науки** — `prereq_ids`, `unlocks_concepts`;
5. **Инженерное применение в XXI веке** — `modern_application`.

Результат кэшируется в ``post.meta["longread_body"]`` (повторный вызов с
``len >= 1200`` возвращает кэш и не ходит в сеть).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from .models import Post

WIKI_API = "https://ru.wikipedia.org/w/api.php"
CACHE_MIN_CHARS = 1200


def _wiki_slug(post: Post, meta: Dict[str, Any]) -> str:
    """Заголовок для Википедии: явный `wiki_title` → учёный → тема поста."""
    for candidate in (meta.get("wiki_title"), meta.get("scientist")):
        text = str(candidate or "").strip()
        if text:
            return text
    title = str(getattr(post, "title", "") or "")
    return title.split(":")[0].split("—")[0].strip()


def _fetch_wiki_extract(slug: str, http_get: Optional[Callable[..., Any]], timeout: float) -> str:
    """Выжимка из ru.wikipedia (через инъектируемый ``http_get``); при сбое — пусто."""
    if not slug or http_get is None:
        return ""
    url = (
        f"{WIKI_API}?action=query&prop=extracts&explaintext=1&redirects=1"
        f"&format=json&titles={quote(slug)}"
    )
    try:
        try:
            payload = http_get(url, timeout=timeout)
        except TypeError:
            payload = http_get(url)
    except Exception:
        return ""
    if payload is None:
        return ""
    if hasattr(payload, "json"):
        try:
            payload = payload.json()
        except Exception:
            return ""
    if not isinstance(payload, dict):
        return ""
    pages = ((payload.get("query") or {}).get("pages") or {})
    for page in pages.values():
        extract = str(page.get("extract") or "").strip()
        if extract:
            return extract
    return ""


def _compose_longread(post: Post, meta: Dict[str, Any], wiki: str) -> str:
    """Собирает пять академических разделов лонгрида."""
    era = str(meta.get("era") or "").strip()
    scientist = str(meta.get("scientist") or "").strip()
    formula = (getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or "").strip()
    variables = str(meta.get("formula_vars") or "").strip()
    proof = meta.get("proof") if isinstance(meta.get("proof"), dict) else {}
    computed = str((proof or {}).get("computed_example") or "").strip()
    prereqs = [str(item) for item in (meta.get("prereq_ids") or [])]
    unlocks = [str(item) for item in (meta.get("unlocks_concepts") or [])]
    modern = str(meta.get("modern_application") or "").strip()

    head: List[str] = []
    section = str(meta.get("section_num") or "").strip()
    if section:
        head.append(f"§ {section}")
    head.append(f"# {post.title}")
    if era or scientist:
        head.append("*" + " · ".join(part for part in (era, scientist) if part) + "*")

    one = ["I. Исторический контекст и постановка задачи"]
    if era or scientist:
        one.append(" · ".join(part for part in (era, scientist) if part) + ".")
    if post.hook:
        one.append(f"Ключевой вопрос: {post.hook}")
    if post.body:
        one.append(post.body.strip())
    if wiki:
        one.append(f"Из энциклопедии: {wiki[:900]}")

    two = ["II. Аналитическая модель и экспликация величин"]
    if formula:
        two.append(f"Формула: {formula}")
    if variables:
        two.append(f"где: {variables}")
    elif meta.get("constants_used"):
        two.append("где: " + ", ".join(str(symbol) for symbol in meta["constants_used"]))
    if len(two) == 1:
        two.append("Модель описывается словесно; формальная запись уточняется.")

    three = ["III. Вычислительная верификация"]
    if computed:
        three.append(computed)
    code_proof = (proof or {}).get("code_proof") or {}
    if code_proof.get("summary"):
        three.append(f"Песочница кода: {code_proof['summary']}")
    if (proof or {}).get("merkle_hash"):
        three.append(f"Печать версии (merkle v1): {str(proof['merkle_hash'])[:32]}…")
    if len(three) == 1:
        three.append("Точный расчёт формируется вычислительным паспортом поста.")

    four = ["IV. Связи в дереве фундамента науки"]
    if prereqs:
        four.append("Опирается на: " + ", ".join(prereqs) + ".")
    if unlocks:
        four.append("Открывает путь к: " + ", ".join(unlocks) + ".")
    if len(four) == 1:
        four.append("Узел фундаментальной программы; связи уточняются по мере роста дерева.")

    five = ["V. Инженерное применение в XXI веке"]
    five.append(modern or "Применение уточняется по мере выхода связанных разборов.")

    body = "\n\n".join(
        part for part in (
            "\n\n".join(head),
            "\n\n".join(one),
            "\n\n".join(two),
            "\n\n".join(three),
            "\n\n".join(four),
            "\n\n".join(five),
        ) if part.strip()
    )
    return body


def enrich_post_longread(
    post: Post, http_get: Optional[Callable[..., Any]] = None, timeout: float = 3.0
) -> str:
    """Возвращает (и кэширует) лонгрид поста из пяти разделов."""
    meta = getattr(post, "meta", None)
    if not isinstance(meta, dict):
        meta = {}
        post.meta = meta
    cached = str(meta.get("longread_body") or "")
    if len(cached) >= CACHE_MIN_CHARS:
        return cached
    wiki = _fetch_wiki_extract(_wiki_slug(post, meta), http_get, timeout)
    text = _compose_longread(post, meta, wiki)
    meta["longread_body"] = text
    return text

