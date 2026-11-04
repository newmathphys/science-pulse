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

import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from .models import Post

WIKI_API = "https://ru.wikipedia.org/w/api.php"
CACHE_MIN_CHARS = 1200
# Сколько символов полной статьи Википедии попадает в главу (не «тизер»).
WIKI_CHARS = 2600

# 🏛 Академический свод / верификатор по дисциплине (второй уровень родословной).
CANONICAL_ARCHIVES: Dict[str, str] = {
    "math": "NIST DLMF (Digital Library of Mathematical Functions) · Lean 4 Mathlib",
    "physics": "NIST CODATA · Particle Data Group",
    "cs": "OEIS Foundation · Rosetta Code · TheAlgorithms",
}

# 📜 Первоисточник (отец идеи) для 30 узлов канона: «источник источника».
PRIMARY_WORKS: Dict[str, str] = {
    "pythagoras": "Евклид, «Начала», Книга I, предложение 47 (ок. 300 г. до н.э.)",
    "euclid_gcd": "Евклид, «Начала», Книга VII, предложения 1–2 (ок. 300 г. до н.э.)",
    "archimedes": "Архимед, «О плавающих телах» (ок. 250 г. до н.э.)",
    "al_khwarizmi": "аль-Хорезми, «Китаб аль-джебр валь-мукабала» (ок. 820 г.)",
    "leibniz_boolean": "Г. Лейбниц, «Об искусстве комбинаторики» (1666)",
    "galileo_fall": "Г. Галилей, «Беседы и математические доказательства» (1638)",
    "newton_gravity": "И. Ньютон, «Математические начала натуральной философии» (1687)",
    "newton_calculus": "И. Ньютон, «Метод флюксий» (1671)",
    "lovelace": "А. Лавлейс, «Примечания к очерку Менабреа» (1843)",
    "bernoulli_flow": "Д. Бернулли, «Гидродинамика» (1738)",
    "euler_identity": "Л. Эйлер, «Введение в анализ бесконечных» (1748)",
    "gauss_normal": "К. Гаусс, «Теория движения небесных тел» (1809)",
    "hoare_sort": "Ч. Хоар, «Quicksort», Computer Journal 5(1) (1962)",
    "boltzmann_entropy": "Л. Больцман, «О связи между вторым началом…» (1877)",
    "fourier_series": "Ж. Фурье, «Аналитическая теория тепла» (1822)",
    "maxwell": "Дж. Максвелл, «Трактат об электричестве и магнетизме» (1873)",
    "noether_symmetry": "Э. Нётер, «Инвариантные вариационные задачи» (1918)",
    "riemann_integral": "Б. Риман, «О представимости функции тригонометрическим рядом» (1854)",
    "dijkstra_shortest": "Э. Дейкстра, «Замечание о двух задачах в связи с графами» (1959)",
    "planck_quantum": "М. Планк, «О законе распределения энергии в нормальном спектре» (1901)",
    "turing_machine": "А. Тьюринг, «О вычислимых числах» (1936)",
    "shannon_entropy": "К. Шеннон, «Математическая теория связи» (1948)",
    "schrodinger": "Э. Шрёдингер, «Квантование как задача о собственных значениях» (1926)",
    "quantum_tunneling": "Г. Гамов, «Мировые константы и квантовая теория» (1928)",
    "godel_incompleteness": "К. Гёдель, «О формально неразрешимых предложениях» (1931)",
    "rsa_crypto": "Р. Ривест, А. Шамир, Л. Адлеман, «Метод получения цифровых подписей» (1978)",
    "einstein_relativity": "А. Эйнштейн, «К электродинамике движущихся тел» (1905)",
    "insar_ndvi": "Х. Зебрискер и др., «Радиолокационная интерферометрия» (1986)",
    "schwarzschild_light": "К. Шварцшильд, «О гравитационном поле точечной массы» (1916)",
    "lj_lorenz": "Э. Лоренц, «Детерминированный непериодический поток» (1963)",
}



def _primary_work(post: Post, meta: Dict[str, Any]) -> str:
    """📜 Первоисточник: точный труд из канона либо учёный + эпоха."""
    canon_id = str(meta.get("foundation_id") or meta.get("canon_id") or "")
    if canon_id in PRIMARY_WORKS:
        return PRIMARY_WORKS[canon_id]
    explicit = str(meta.get("primary_work") or "").strip()
    if explicit:
        return explicit
    scientist = str(meta.get("scientist") or "").strip()
    era = str(meta.get("era") or "").strip()
    if scientist:
        return f"{scientist}, оригинальный труд ({era or 'эпоха открытия'})"
    return "Первоисточник уточняется по мере выхода связанных разборов"


def _references_from_extract(extract: str, limit: int = 6) -> List[str]:
    """Библиографические ссылки из разделов «Литература» и «Примечания» статьи."""
    if not extract:
        return []
    parts = re.split(r"\n=+\s*([^=\n]+?)\s*=+\s*\n", extract)
    wanted = ("литератур", "примечан", "источник", "ссылк")
    found: List[str] = []
    for index in range(1, len(parts) - 1, 2):
        heading = parts[index].strip().lower()
        if not any(marker in heading for marker in wanted):
            continue
        for line in parts[index + 1].split("\n"):
            cleaned = line.strip(" *\t")
            if len(cleaned) > 12:
                found.append(cleaned)
            if len(found) >= limit:
                return found
    return found[:limit]


def build_source_lineage(post: Post, extract: str = "") -> Dict[str, Any]:
    """Трехуровневая родословная первоисточников («источник источника»)."""
    meta = post.meta if isinstance(getattr(post, "meta", None), dict) else {}
    existing = meta.get("source_lineage")
    if isinstance(existing, dict) and existing.get("primary_work"):
        return existing
    domain = str(getattr(post, "domain", "math") or "math")
    references = _references_from_extract(extract)
    if not references and getattr(post, "source_url", ""):
        references = [str(post.source_url)]
    return {
        "primary_work": _primary_work(post, meta),
        "canonical_archive": CANONICAL_ARCHIVES.get(domain, "NIST CODATA · OEIS"),
        "digital_source": {
            "name": str(getattr(post, "source_name", "") or "Википедия"),
            "url": str(getattr(post, "source_url", "") or ""),
        },
        "references": references,
    }


def lineage_line(lineage: Dict[str, Any]) -> str:
    """Однострочная печать родословной (для лонгрида, сайта и радио)."""
    digital = lineage.get("digital_source") or {}
    refs = lineage.get("references") or []
    tail = f" Библиография: {'; '.join(str(item) for item in refs[:3])}." if refs else ""
    return (
        f"📜 Родословная первоисточников: первоисточник — {lineage.get('primary_work')}; "
        f"академический свод — {lineage.get('canonical_archive')}; "
        f"цифровой узел — {digital.get('name') or '—'}.{tail}"
    )


def _wiki_slug(post: Post, meta: Dict[str, Any]) -> str:
    """Заголовок для Википедии: явный `wiki_title` → учёный → тема поста."""
    for candidate in (meta.get("wiki_title"), meta.get("scientist")):
        text = str(candidate or "").strip()
        if text:
            return text
    title = str(getattr(post, "title", "") or "")
    return title.split(":")[0].split("—")[0].strip()


def _fetch_wiki(
    slug: str, http_get: Optional[Callable[..., Any]], timeout: float
) -> Dict[str, Any]:
    """Полная статья ru.wikipedia + формулы `<math>` ОДНИМ запросом (без `exintro`).

    Возвращает ``{"extract": str, "formulas": [str]}``; при сбое — пустые значения.
    """
    empty: Dict[str, Any] = {"extract": "", "formulas": []}
    if not slug or http_get is None:
        return empty
    url = (
        f"{WIKI_API}?action=query&prop=extracts|revisions&explaintext=1&redirects=1"
        f"&rvprop=content&rvslots=main&format=json&titles={quote(slug)}"
    )
    try:
        try:
            payload = http_get(url, timeout=timeout)
        except TypeError:
            payload = http_get(url)
    except Exception:
        return empty
    if payload is None:
        return empty
    if hasattr(payload, "json"):
        try:
            payload = payload.json()
        except Exception:
            return empty
    if not isinstance(payload, dict):
        return empty
    pages = ((payload.get("query") or {}).get("pages") or {})
    for page in pages.values():
        extract = str((page or {}).get("extract") or "").strip()
        wikitext = ""
        for revision in (page or {}).get("revisions") or []:
            slots = (revision or {}).get("slots") or {}
            main = slots.get("main") if isinstance(slots, dict) else None
            if isinstance(main, dict):
                wikitext = str(main.get("*") or main.get("content") or "")
            elif isinstance(revision, dict) and revision.get("*"):
                wikitext = str(revision["*"])
            if wikitext:
                break
        formulas = [item.strip() for item in re.findall(r"<math>(.*?)</math>", wikitext, re.S)]
        return {"extract": extract, "formulas": [item for item in formulas if item][:8]}
    return empty


def _fetch_wiki_extract(slug: str, http_get: Optional[Callable[..., Any]], timeout: float) -> str:
    """Только текст статьи (совместимость со старым вызовом)."""
    return str(_fetch_wiki(slug, http_get, timeout).get("extract") or "")


def _compose_longread(
    post: Post,
    meta: Dict[str, Any],
    wiki: str,
    formulas: Optional[List[str]] = None,
    lineage: Optional[Dict[str, Any]] = None,
) -> str:
    """Собирает пять академических разделов лонгрида (глубина 3 500–9 000 знаков)."""
    formulas = list(formulas or [])
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
        one.append(f"Из энциклопедии: {wiki[:WIKI_CHARS]}")

    two = ["II. Аналитическая модель и экспликация величин"]
    if formula:
        two.append(f"Формула: {formula}")
    if variables:
        two.append(f"где: {variables}")
    elif meta.get("constants_used"):
        two.append("где: " + ", ".join(str(symbol) for symbol in meta["constants_used"]))
    if formulas:
        two.append(
            "Формулы из первоисточника: "
            + "; ".join(f"${item}$" for item in formulas[:5])
        )
    if len(two) == 1:
        two.append("Модель описывается словесно; формальная запись уточняется.")

    three = ["III. Вычислительная верификация"]
    if computed:
        three.append(computed)
    challenge = meta.get("challenge") if isinstance(meta.get("challenge"), dict) else None
    if not challenge:
        try:
            from .challenge import build_challenge

            challenge = build_challenge(post)
        except Exception:
            challenge = None
    if challenge:
        three.append("🧠 Задача для самопроверки: " + str(challenge.get("question") or ""))
        three.append(
            "Ответ ядра: " + str(challenge.get("answer") or "")
            + ". " + str(challenge.get("explanation") or "")
        )
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
    if lineage:
        four.append(lineage_line(lineage))
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
    if not isinstance(meta.get("source_lineage"), dict):
        meta["source_lineage"] = build_source_lineage(post)
    cached = str(meta.get("longread_body") or "")
    if len(cached) >= CACHE_MIN_CHARS:
        return cached
    wiki = _fetch_wiki(_wiki_slug(post, meta), http_get, timeout)
    extract = str(wiki.get("extract") or "")
    lineage = build_source_lineage(post, extract=extract)
    meta["source_lineage"] = lineage
    text = _compose_longread(post, meta, extract, wiki.get("formulas") or [], lineage)
    meta["longread_body"] = text
    return text

