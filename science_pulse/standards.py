"""Контур качества: 8-рубежный `StandardsChecker` с авто-лечением и карантином.

Рубежи (гейты) проверки подписи и карточки перед публикацией:

1. `cyrillic`   — доля кириллицы ≥ `min_cyrillic_ratio` (пост переведён);
2. `length`     — в описании ≥ `min_letters` букв (не обрубок);
3. `raw_latex`  — в подписи нет сырых `\\frac`, `\\sqrt`, `$$`, `$`;
4. `brackets`   — сбалансированы скобки и математические доллары;
5. `code_ast`   — код поста разбирается `ast.parse`;
6. `card`       — карточка ровно 1080×1080 и тяжелее `min_card_bytes`;
7. `html`       — сбалансированы HTML-теги Telegram (`b`, `i`, `a`, `code`, `pre`, `u`, `s`);
8. `translation_seam` — нет технических следов машинного перевода (маски, пробелы перед знаками, пустые скобки).

При нарушении: `heal()` пытается починить (Unicode-формулы, обрезка по
предложению, перевод), иначе пост уходит в карантин (`status='rejected'`).
Пороги настраиваются: `standards set <key> <value>` в пульте или
`cli standards set`.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Post

LOGGER = logging.getLogger(__name__)

HTML_TAGS = ("b", "strong", "i", "em", "u", "s", "code", "pre", "a", "blockquote", "tg-spoiler")


@dataclass
class Standards:
    """Пороги качества (настраиваются из kv/config)."""

    min_cyrillic_ratio: float = 0.42
    min_letters: int = 200
    max_caption: int = 1024
    min_card_bytes: int = 15_000
    card_size: int = 1080
    check_code_ast: bool = True
    max_translation_seams: int = 3

    DEFAULTS = {
        "min_cyrillic_ratio": 0.42,
        "min_letters": 200,
        "max_caption": 1024,
        "min_card_bytes": 15_000,
        "card_size": 1080,
        "check_code_ast": True,
        "max_translation_seams": 3,
    }

    @classmethod
    def from_config(cls, config: Any) -> "Standards":
        raw = dict((getattr(config, "raw", {}) or {}).get("standards") or {})
        values = dict(cls.DEFAULTS)
        values.update({key: value for key, value in raw.items() if key in cls.DEFAULTS})
        # Ожидаемый размер карточки берём из `card.size`: иначе смена размера в
        # конфиге расходится с контуром качества и в карантин уходит КАЖДЫЙ пост.
        card = (getattr(config, "raw", {}) or {}).get("card") or {}
        try:
            size = int(card.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        if size > 0 and "card_size" not in raw:
            values["card_size"] = size
        return cls(**values)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "min_cyrillic_ratio": self.min_cyrillic_ratio,
            "min_letters": self.min_letters,
            "max_caption": self.max_caption,
            "min_card_bytes": self.min_card_bytes,
            "card_size": self.card_size,
            "check_code_ast": self.check_code_ast,
            "max_translation_seams": self.max_translation_seams,
        }

    @classmethod
    def parse_value(cls, key: str, value: str) -> Any:
        default = cls.DEFAULTS.get(key)
        if isinstance(default, bool):
            return str(value).strip().lower() in ("1", "true", "да", "yes", "on")
        if isinstance(default, int):
            return int(float(value))
        return float(value)


@dataclass
class Violation:
    code: str
    detail: str


@dataclass
class Report:
    ok: bool
    violations: List[Violation] = field(default_factory=list)
    healed: List[str] = field(default_factory=list)
    checked: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "violations": [{"code": v.code, "detail": v.detail} for v in self.violations],
            "healed": self.healed,
        }


def cyrillic_ratio(text: str) -> float:
    """Доля кириллических букв среди всех букв текста."""
    letters = [char for char in (text or "") if char.isalpha()]
    if not letters:
        return 0.0
    cyrillic = [char for char in letters if "а" <= char.lower() <= "я" or char.lower() == "ё"]
    return len(cyrillic) / len(letters)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def brackets_balanced(text: str) -> Tuple[bool, str]:
    """Проверяет баланс (), [], {} и чётность математических долларов."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: List[str] = []
    for char in text or "":
        if char in "([{":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return False, f"лишняя скобка {char}"
    if stack:
        return False, f"не закрыта скобка {stack[-1]}"
    if (text or "").count("$$") % 2 != 0:
        return False, "непарные $$"
    single = (text or "").replace("$$", "").count("$")
    if single % 2 != 0:
        return False, "непарный $"
    return True, ""


def html_balanced(text: str) -> Tuple[bool, str]:
    """Баланс HTML-тегов Telegram (открыт/закрыт)."""
    for tag in HTML_TAGS:
        opened = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", text or "", flags=re.I))
        closed = len(re.findall(rf"</{tag}>", text or "", flags=re.I))
        if opened != closed:
            return False, f"<{tag}>: открыт {opened}, закрыт {closed}"
    return True, ""


class StandardsChecker:
    """Проверяет и лечит посты перед публикацией (8 рубежей)."""

    def __init__(self, standards: Optional[Standards] = None):
        self.standards = standards or Standards()

    @classmethod
    def load(cls, storage: Any, config: Any = None) -> "StandardsChecker":
        """Пороги: умолчания ← конфиг ← kv (оператор менял через `/standards set`).

        `config` задаёт ожидаемый размер карточки из `card.size`, чтобы контур
        качества не расходился с реально нарисованной карточкой.
        """
        import json

        base = Standards.from_config(config) if config is not None else Standards(**Standards.DEFAULTS)
        values = dict(base.as_dict())
        raw = storage.kv_get("standards", "") if hasattr(storage, "kv_get") else ""
        if raw:
            try:
                stored = json.loads(raw)
                if isinstance(stored, dict):
                    values.update({key: value for key, value in stored.items()
                                   if key in Standards.DEFAULTS})
            except ValueError:
                pass
        return cls(Standards(**values))

    def save(self, storage: Any) -> None:
        import json

        storage.kv_set("standards", json.dumps(self.standards.as_dict(), ensure_ascii=False))

    def check(self, post: Post, caption: str, card: Any = None) -> Report:
        """Прогоняет все рубежи и возвращает отчёт."""
        violations: List[Violation] = []
        checked = 0
        plain = _strip_html(caption)

        checked += 1
        ratio = cyrillic_ratio(plain)
        if ratio < self.standards.min_cyrillic_ratio:
            violations.append(Violation("cyrillic", f"кириллицы {ratio:.0%} < {self.standards.min_cyrillic_ratio:.0%}"))

        checked += 1
        letters = sum(1 for char in plain if char.isalpha())
        if letters < self.standards.min_letters:
            violations.append(Violation("length", f"букв {letters} < {self.standards.min_letters}"))

        checked += 1
        for pattern, label in ((r"\\frac", r"\frac"), (r"\\sqrt", r"\sqrt"), (r"\$\$", "$$")):
            if re.search(pattern, caption):
                violations.append(Violation("raw_latex", f"сырой LaTeX в подписи: {label}"))
                break

        checked += 1
        balanced, detail = brackets_balanced(caption)
        if not balanced:
            violations.append(Violation("brackets", detail))

        checked += 1
        if self.standards.check_code_ast and (post.code or "").strip():
            try:
                ast.parse(post.code)
            except SyntaxError as exc:
                violations.append(Violation("code_ast", f"код не парсится: {exc.msg}"))

        if card is not None:
            checked += 1
            width = getattr(card, "width", 0)
            height = getattr(card, "height", 0)
            size = getattr(card, "data", b"") or b""
            if (width, height) != (self.standards.card_size, self.standards.card_size):
                violations.append(Violation("card", f"размер {width}×{height} ≠ {self.standards.card_size}"))
            else:
                # Порог веса масштабируется с размером: маленькая карточка
                # не должна уходить в карантин только из-за меньшего PNG.
                threshold = max(2_000, int(self.standards.min_card_bytes * min(width, height) / 1080))
                if len(size) < threshold:
                    violations.append(Violation("card", f"вес {len(size)} < {threshold}"))

        checked += 1
        balanced, detail = html_balanced(caption)
        if not balanced:
            violations.append(Violation("html", detail))

        checked += 1
        from .text import check_unmapped_latex, clean_latex_for_telegram

        formula_raw = str(getattr(post, "formula_latex", "") or getattr(post, "formula_plain", "") or "")
        unknown = check_unmapped_latex(formula_raw)
        if unknown:
            violations.append(Violation(
                "cross_modal",
                "неизвестные LaTeX-команды: " + ", ".join("\\" + item for item in unknown),
            ))
        cleaned_formula = clean_latex_for_telegram(formula_raw)
        if re.search(r"\bA\s+B\b|\bB\s+A\b", cleaned_formula):
            violations.append(Violation(
                "cross_modal",
                "в формуле пропал оператор между переменными",
            ))

        checked += 1
        from .text import translation_seam_score

        seam_score, seam_details = translation_seam_score(plain)
        if seam_score > self.standards.max_translation_seams:
            violations.append(Violation(
                "translation_seam",
                f"шов перевода {seam_score} > {self.standards.max_translation_seams}: "
                + ", ".join(seam_details),
            ))

        return Report(ok=not violations, violations=violations, checked=checked)

    def heal(self, post: Post, caption: str) -> Tuple[Post, str, List[str]]:
        """Авто-лечение: Unicode-формулы, перевод, обрезка, закрытие тегов."""
        from .text import clean_latex_for_telegram, translate_preserving_latex

        notes: List[str] = []
        healed_caption = clean_latex_for_telegram(caption or "")
        if healed_caption != (caption or ""):
            notes.append("latex→unicode")

        plain = _strip_html(healed_caption)
        if cyrillic_ratio(plain) < self.standards.min_cyrillic_ratio:
            translated = translate_preserving_latex(healed_caption)
            if translated and cyrillic_ratio(_strip_html(translated)) > cyrillic_ratio(plain):
                healed_caption = translated
                notes.append("перевод")

        if len(healed_caption) > self.standards.max_caption:
            cut = healed_caption[: self.standards.max_caption]
            index = cut.rfind(". ")
            healed_caption = (cut[: index + 1] if index > 0 else cut).rstrip()
            notes.append("обрезка по предложению")

        for tag in HTML_TAGS:
            opened = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", healed_caption, flags=re.I))
            closed = len(re.findall(rf"</{tag}>", healed_caption, flags=re.I))
            if opened > closed:
                healed_caption += f"</{tag}>" * (opened - closed)
                notes.append(f"закрыт <{tag}>")
        return post, healed_caption, notes

    def enforce(self, post: Post, caption: str, card: Any, storage: Any) -> Tuple[Report, Post, str]:
        """Проверка → лечение → карантин. Возвращает (отчёт, пост, подпись)."""
        report = self.check(post, caption, card)
        if report.ok:
            return report, post, caption
        post, healed_caption, notes = self.heal(post, caption)
        retry = self.check(post, healed_caption, card)
        retry.healed = notes
        if retry.ok:
            LOGGER.info("Стандарты: пост %s вылечен (%s)", post.id, ", ".join(notes) or "без правок")
            return retry, post, healed_caption
        self.quarantine(post, retry, storage)
        return retry, post, healed_caption

    def quarantine(self, post: Post, report: Report, storage: Any) -> None:
        """Карантин: пост не выходит, статус `rejected`, причина в meta/kv."""
        reasons = "; ".join(f"{item.code}: {item.detail}" for item in report.violations)[:400]
        try:
            storage.update_post_fields(post.id, {"status": "rejected"})
            storage.set_post_meta(post.id, "rejected_reason", reasons)
            counter = storage.kv_int("quarantine_count", 0) + 1
            storage.kv_set("quarantine_count", str(counter))
            LOGGER.warning("Карантин %s: %s", post.id, reasons)
        except Exception as exc:
            LOGGER.warning("Карантин не записан: %s", exc)

    @staticmethod
    def list_quarantine(storage: Any, limit: int = 50) -> List[Post]:
        return storage.list_posts(status="rejected", limit=limit, order="created_at DESC")