from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..models import Post, make_id
from ..text import clean_text, truncate
from .base import Source, SourceError

DEFAULT_SEQUENCES = [
    "A000045",  # Фибоначчи
    "A000108",  # Каталан
    "A000079",  # степени двойки
    "A000040",  # простые числа
    "A000984",  # центральные биномиальные
    "A001353",  # 3x3 матрицы
    "A000129",  # Пелль
    "A001622",  # золотое сечение (цифры)
    "A005132",  # Recamán
    "A000203",  # сумма делителей
]

XREF_RE = re.compile(r"(A\d{6})")


class OEISSource(Source):
    name = "oeis"
    domains = ("math",)
    tier = "online"

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        options = self.config.source_options(self.name)
        sequences = options.get("sequences") or DEFAULT_SEQUENCES
        if not sequences:
            return []

        posts: List[Post] = []
        attempts = min(max(limit, 1), len(sequences))
        for offset in range(attempts):
            seq_id = sequences[(cycle + offset) % len(sequences)]
            try:
                post = self.fetch_sequence(seq_id)
            except SourceError as exc:
                if offset == attempts - 1 and not posts:
                    raise
                continue
            if post:
                posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def fetch_sequence(self, seq_id: str) -> Optional[Post]:
        data = self.http.get_json(
            "https://oeis.org/search",
            params={"q": f"id:{seq_id}", "fmt": "json"},
        )
        items: List[Dict[str, Any]] = []
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            raw = data.get("results")
            if isinstance(raw, list):
                items = [item for item in raw if isinstance(item, dict)]
        if not items:
            return None

        item = items[0]
        number = item.get("number")
        formatted_id = f"A{int(number):06d}" if number is not None else seq_id
        name = clean_text(item.get("name") or "", max_len=220)
        values_full = (item.get("data") or "").strip()
        values_raw = clean_text(values_full, max_len=600)
        value_items = [part.strip() for part in values_raw.split(",") if part.strip()]
        if len(values_full) > len(values_raw) and value_items:
            # Хвост обрезан посередине числа — отбрасываем неполный последний член.
            value_items = value_items[:-1]
        first_values = ", ".join(value_items[:6])
        values_suffix = "…" if len(value_items) > 6 else ""
        values = f"{first_values}{values_suffix}"
        formulas = [clean_text(f, max_len=220) for f in (item.get("formula") or []) if f]
        formula = self._pick_formula(formulas, values)
        python_code = self._pick_python(item.get("program") or [])
        xrefs = XREF_RE.findall(" ".join(item.get("xref") or []))

        name_ru = self._translate(name).rstrip(".")
        title = truncate(f"OEIS {formatted_id}: {name_ru}", 200)
        hook = self._translate(f"Какой закон скрыт в последовательности {values}?")
        formula_text = (formula or "последовательность задаётся рекуррентно").rstrip(".")
        body = f"{name_ru}. Первые члены: {values}. Свойство: {formula_text}."
        post = Post(
            id=make_id(self.name, formatted_id),
            domain="math",
            title=title,
            hook=hook,
            body=clean_text(body, max_len=900),
            formula_latex=formula,
            formula_plain=formula,
            code=python_code,
            source_name=f"OEIS {formatted_id}",
            source_url=f"https://oeis.org/{formatted_id}",
            tier=self.tier,
            meta={"oeis_id": formatted_id, "xrefs": list(dict.fromkeys(xrefs))[:6], "sequence": value_items[:24]},
        )
        post.quality = post.quality_score()
        return post

    @staticmethod
    def _pick_formula(formulas: List[str], values: str) -> str:
        for formula in formulas:
            if any(marker in formula for marker in ("a(n)", "=", "G.f.", "E.g.f.")):
                return truncate(formula, 200)
        if formulas:
            return truncate(formulas[0], 200)
        return f"a(n): {truncate(values, 80)}" if values else ""

    @staticmethod
    def _pick_python(programs: List[str]) -> str:
        for program in programs:
            if "(Python)" in program:
                code = program.replace("(Python)", "", 1).strip()
                return truncate(code, 420)
        return ""
