"""PDF-книга проекта: все опубликованные посты в академической вёрстке Typst.

Сборка в `dist/science_pulse_book.pdf` (типографика LaTeX-класса):

- титульный лист и автоматическое оглавление (`#outline()`);
- главы по дисциплинам: Математика, Физика, Информатика;
- формулы — настоящим математическим движком (Computer Modern, matplotlib
  mathtext), карточки постов — как иллюстрации;
- предметный указатель учёных со ссылками на главы (`#link(<p-…>)`).

Компилятор — уже установленный пакет `typst` (typst-py). Формулы намеренно
вставляются картинками, а не Typst-мат: так сборка детерминирована и не падает
на различиях синтаксиса LaTeX.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .models import DOMAIN_LABELS, Post
from .storage import Storage

LOGGER = logging.getLogger(__name__)

DOMAIN_ORDER = ("math", "physics", "cs")


def typst_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("typst") is not None


def _esc(value: Any) -> str:
    from .cards3b1b import _esc_typst

    return _esc_typst(value)


def _str(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def build_typst_source(posts: List[Post], card_names: Dict[str, str], formula_names: Dict[str, str],
                       constants_rows: List[tuple], generated_at: str) -> str:
    """Собирает исходник Typst-книги по постам (детерминированно)."""
    sections: List[str] = []
    index_entries: List[str] = []

    chapter_titles = {"math": "Математика", "physics": "Физика", "cs": "Информатика"}
    for domain in DOMAIN_ORDER:
        members = [post for post in posts if post.domain == domain]
        if not members:
            continue
        sections.append(f"= {chapter_titles.get(domain, DOMAIN_LABELS.get(domain, domain.title()))}")
        for post in members:
            label = f"p-{post.id}"
            meta = post.meta or {}
            sections.append(f"== {_esc(post.title)} <{label}>")
            if meta.get("scientist") or meta.get("era"):
                line = " · ".join(part for part in (str(meta.get("era", "")), str(meta.get("scientist", ""))) if part)
                sections.append(f"#emph[{_esc(line)}]")
            if post.hook:
                sections.append(f'#text(weight: "semibold")[{_esc(post.hook)}]')
            card = card_names.get(post.id)
            if card:
                sections.append(f"#figure(image({_str(card)}, width: 58%), caption: [Карточка поста])")
            formula = formula_names.get(post.id)
            if formula:
                sections.append(
                    f"#figure(image({_str(formula)}, width: 82%), caption: [{_esc(post.formula_plain or 'Формула')}])"
                )
            elif post.formula_plain:
                sections.append(f"#align(center)[#text(size: 12pt)[{_esc(post.formula_plain)}]]")
            body = str((getattr(post, "meta", {}) or {}).get("longread_body") or "").strip() \
                or (post.body or post.hook or "").strip()
            for paragraph in [chunk.strip() for chunk in body.split("\n") if chunk.strip()][:6]:
                sections.append(f"#par[{_esc(paragraph)}]")
            if post.code:
                sections.append(f'#raw({_str(post.code)}, lang: "python", block: true)')
            application = str(meta.get("modern_application") or "").strip()
            if application:
                sections.append(f'#text(fill: rgb("#8B2635"))[Где работает сегодня: {_esc(application)}]')
            sections.append(f'#text(size: 9pt, fill: rgb("#6B6458"))[Источник: {_esc(post.source_name)}]')
            sections.append("")
            if meta.get("scientist"):
                index_entries.append(f"- #link(<{label}>)[{_esc(str(meta.get('scientist')))}] — {_esc(post.title)}")

    constants_block = ["= Словарь фундаментальных констант"]
    for symbol, name, value, unit in constants_rows:
        constants_block.append(f"- *{_esc(symbol)}* — {_esc(name)}: `{_esc(value)}` {_esc(unit)}")

    joined_sections = "\n".join(sections)
    joined_constants = "\n".join(constants_block)
    joined_index = "\n".join(index_entries) or "- Учёные появятся вместе с постами канона."
    return f"""
#set text(font: ("DejaVu Serif", "Liberation Serif"), size: 11pt, lang: "ru")
#set page(paper: "a5", margin: (x: 2cm, y: 2.2cm))

#page(numbering: none)[
  #v(3fr)
  #align(center)[
    #text(size: 28pt, weight: "bold")[Science Pulse]
    #v(10pt)
    #text(size: 14pt, style: "italic")[Научная книга проекта]
    #v(6pt)
    #text(size: 12pt)[Математика · Физика · Информатика]
    #v(24pt)
    #text(size: 11pt)[Детерминированная фабрика контента: тексты из открытых источников,
    формулы настоящим математическим движком, 0 LLM в контенте.]
    #v(10pt)
    #text(size: 10pt, fill: rgb("#6B6458"))[Собрано: {generated_at} · постов: {len(posts)}]
  ]
  #v(2fr)
]

#set page(numbering: "1")
#outline(title: "Оглавление", depth: 2)
#pagebreak()

{joined_sections}

{joined_constants}

= Предметный указатель учёных
{joined_index}
"""


class BookBuilder:
    """Собирает PDF-книгу из опубликованных постов через typst-py."""

    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage

    def build(self, out_pdf: str | Path | None = None, limit: Optional[int] = None) -> Path:
        if not typst_available():
            raise RuntimeError("пакет typst не установлен: pip install typst")
        import shutil

        import typst

        from .cards_academic import render_formula_png
        from .constants import CONSTANTS, format_value

        out_path = Path(out_pdf) if out_pdf else self.config.dist_dir / "science_pulse_book.pdf"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        posts = self.storage.list_posts(status="published", limit=limit or 1000, order="published_at ASC")
        if not posts:
            posts = self.storage.list_posts(status="ready", limit=limit or 100, order="created_at ASC")
        if not posts:
            raise RuntimeError("нет постов для книги: запустите harvest/publish")

        constants_rows = [
            (item["symbol"], item["name"], format_value(item["value"]), item["unit"]) for item in CONSTANTS
        ]
        generated_at = max((post.published_at or post.created_at or "") for post in posts)[:10]

        with tempfile.TemporaryDirectory(prefix="sp_book_") as tmp:
            root = Path(tmp)
            cards_dir = root / "cards"
            cards_dir.mkdir()
            card_names: Dict[str, str] = {}
            formula_names: Dict[str, str] = {}
            for post in posts:
                card = Path(post.card_path) if post.card_path else self.config.cards_dir / f"{post.id}.png"
                if card.is_file():
                    shutil.copyfile(card, cards_dir / f"{post.id}.png")
                    card_names[post.id] = f"cards/{post.id}.png"
                formula = post.formula_latex or post.formula_plain
                if formula and render_formula_png(formula, root / f"formula_{post.id}.png", fontset="cm"):
                    formula_names[post.id] = f"formula_{post.id}.png"

            source = build_typst_source(posts, card_names, formula_names, constants_rows, generated_at)
            typ_file = root / "book.typ"
            typ_file.write_text(source, encoding="utf-8")
            typst.compile(str(typ_file), output=str(out_path), root=str(root), format="pdf")
        LOGGER.info("Книга собрана: %s (%d постов)", out_path, len(posts))
        return out_path