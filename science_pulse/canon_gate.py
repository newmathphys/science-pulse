"""Приёмочная комиссия канона: Two-Pass проверка, авто-доводка и N+1 staging.

`CanonGate(storage, config).verify_and_enforce(post, card_path, caption)`:

- **Pass 1 — канон контента и раздела**: доля кириллицы (если включён перевод),
  длина тела, отсутствие сырого LaTeX в подписи, непустой паспорт канона
  (`era`, `scientist`, `modern_application`, `formula_vars` — пустые поля
  авто-заполняются дефолтами дисциплины) и правило раздела
  (math — баланс скобок; physics — формула + `constants_used`/применение;
  cs — валидный `ast.parse` кода или `O(...)`);
- **Pass 2 — канон медиа и подписи**: карточка существует, 1080×1080, ≥15 КБ,
  `std(pixels) ≥ 5`, внешнее поле не залито тёмным; длина и баланс HTML-тегов.

Если после авто-доводки остаются нарушения — пост переводится в `rejected`
с причинами в `meta["reject_reasons"]`, и пайплайн берёт следующий.

`stage_next(pipeline)` — N+1 warm staging: готовит следующий `ready`-пост
(лонгрид + вычислительный паспорт + карточка + приёмка) и кладёт его id
в `kv["staged_next_post_id"]` (команды `cli staged` и `/staged`).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Post
from .standards import brackets_balanced, cyrillic_ratio, html_balanced

DEFAULT_FILLERS: Dict[str, Dict[str, str]] = {
    "math": {
        "era": "Классическая эпоха",
        "scientist": "Математическая традиция",
        "modern_application": "вычислительная математика, численные методы, машинное обучение",
    },
    "physics": {
        "era": "Новое время",
        "scientist": "Физическая традиция",
        "modern_application": "инженерия, метрология, приборостроение",
    },
    "cs": {
        "era": "XX век",
        "scientist": "Информатическая традиция",
        "modern_application": "программная инженерия, обработка данных, криптография",
    },
}

RAW_LATEX_IN_CAPTION = (r"\frac{", r"\begin{", "$$")
CARD_SIZE = 1080
CARD_MIN_BYTES = 15_000
CARD_MIN_STD = 5.0
BORDER_PX = 15


class CanonGate:
    def __init__(self, storage: Any, config: Any):
        self.storage = storage
        self.config = config

    def verify_and_enforce(self, post: Post, card_path: str = "", caption: str = "") -> Dict[str, Any]:
        meta = post.meta if isinstance(post.meta, dict) else {}
        pass1 = self._pass1_content(post, meta, caption)
        pass2 = self._pass2_media(card_path or getattr(post, "card_path", ""), caption)
        reasons = pass1 + pass2
        result = {"ok": not reasons, "reasons": reasons, "pass1": pass1, "pass2": pass2}
        if reasons:
            post.status = "rejected"
            meta["reject_reasons"] = reasons
            try:
                self.storage.update_post_fields(post.id, {"status": "rejected"})
                self.storage.set_post_meta(post.id, "reject_reasons", reasons)
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # Pass 1 — контент и раздел
    # ------------------------------------------------------------------
    def _pass1_content(self, post: Post, meta: Dict[str, Any], caption: str) -> List[str]:
        reasons: List[str] = []
        body = (post.body or "").strip()
        if bool(getattr(self.config, "translate", False)):
            if cyrillic_ratio(f"{post.title} {body}") < 0.42:
                try:
                    from .text import translate_preserving_latex

                    translated = translate_preserving_latex(body)
                    if translated and translated != body:
                        post.body = translated
                        body = translated.strip()
                except Exception:
                    pass
                if cyrillic_ratio(f"{post.title} {body}") < 0.42:
                    reasons.append("PASS1: доля кириллицы < 0.42")
        if len(body) < 200:
            reasons.append("PASS1: тело < 200 символов")
        for token in RAW_LATEX_IN_CAPTION:
            if token in (caption or ""):
                reasons.append(f"PASS1: сырой LaTeX в подписи ({token})")
                break

        filler = DEFAULT_FILLERS.get(post.domain, DEFAULT_FILLERS["math"])
        for key, value in filler.items():
            if not str(meta.get(key) or "").strip():
                meta[key] = value
                self._persist_meta(post.id, key, value)
        if not str(meta.get("formula_vars") or "").strip() and (post.formula_plain or post.formula_latex):
            used = ", ".join(str(symbol) for symbol in (meta.get("constants_used") or []))
            variables = f"где: {used}" if used else "где: величины формулы"
            meta["formula_vars"] = variables
            self._persist_meta(post.id, "formula_vars", variables)

        formula = (post.formula_plain or post.formula_latex or "").strip()
        if post.domain == "math":
            if formula and not brackets_balanced(formula)[0]:
                reasons.append("PASS1: несбалансированные скобки формулы (math)")
        elif post.domain == "physics":
            if not formula:
                reasons.append("PASS1: у физики нет формулы")
            if not (meta.get("constants_used") or str(meta.get("modern_application") or "").strip()):
                reasons.append("PASS1: у физики нет constants_used/modern_application")
        elif post.domain == "cs":
            code = (post.code or "").strip()
            code_ok = False
            if code:
                try:
                    ast.parse(code)
                    code_ok = True
                except SyntaxError:
                    code_ok = False
            if not code_ok and not re.search(r"O\([^)]*\)", f"{formula} {body}"):
                reasons.append("PASS1: у cs нет валидного кода или O(...)")
        return reasons

    def _persist_meta(self, post_id: str, key: str, value: Any) -> None:
        try:
            self.storage.set_post_meta(post_id, key, value)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Pass 2 — медиа и подпись
    # ------------------------------------------------------------------
    def _pass2_media(self, card_path: str, caption: str) -> List[str]:
        reasons: List[str] = []
        path = Path(card_path) if card_path else None
        if not path or not path.is_file():
            reasons.append("PASS2: карточка не найдена")
        else:
            try:
                from PIL import Image, ImageStat

                with Image.open(path) as image:
                    rgb = image.convert("RGB")
                    if rgb.size != (CARD_SIZE, CARD_SIZE):
                        reasons.append(f"PASS2: размер {rgb.size[0]}×{rgb.size[1]} ≠ {CARD_SIZE}×{CARD_SIZE}")
                    if path.stat().st_size < CARD_MIN_BYTES:
                        reasons.append(f"PASS2: вес < {CARD_MIN_BYTES // 1000} КБ")
                    gray = rgb.convert("L")
                    deviation = ImageStat.Stat(gray).stddev
                    if deviation and deviation[0] < CARD_MIN_STD:
                        reasons.append(f"PASS2: карточка однотонная (std < {CARD_MIN_STD})")
                    band = gray.crop((0, 0, rgb.width, BORDER_PX))
                    histogram = band.histogram()
                    total = sum(histogram) or 1
                    dark_fraction = sum(histogram[:100]) / total
                    if dark_fraction > 0.5:
                        reasons.append("PASS2: внешнее поле залито тёмным (текст в поле)")
            except Exception as exc:
                reasons.append(f"PASS2: карточка не читается ({exc})")
        limit = 1024
        if len(caption or "") > limit:
            reasons.append(f"PASS2: подпись {len(caption)} > {limit}")
        if caption and not html_balanced(caption)[0]:
            reasons.append("PASS2: несбалансированные HTML-теги")
        return reasons

    # ------------------------------------------------------------------
    # N+1 warm staging
    # ------------------------------------------------------------------
    def _stage_post(self, post: Post, enforce: bool = True, render_card: bool = True) -> Dict[str, Any]:
        from .enricher import enrich_post_longread
        from .post_proof import build_post_proof

        try:
            build_post_proof(post)
            enrich_post_longread(post)
        except Exception:
            pass
        card_path = ""
        if render_card:
            try:
                from .cards import render_card

                out = Path(self.config.cards_dir) / f"{post.id}.png"
                card = render_card(post, out_path=out, engine="auto")
                card_path = str(card.path) if card else ""
            except Exception:
                card_path = ""
        if card_path:
            post.card_path = card_path
        if enforce:
            report = self.verify_and_enforce(post, card_path=card_path)
        else:
            report = {
                "ok": True,
                "pass1": [],
                "pass2": [],
                "enforced": False,
                "reasons": [] if card_path else ["карточка будет отрендерена при публикации"],
            }
        try:
            self.storage.set_post_meta(post.id, "longread_body", str((post.meta or {}).get("longread_body") or ""))
            if card_path:
                self.storage.set_post_meta(post.id, "card_path", card_path)
        except Exception:
            pass
        return {
            "ok": bool(report["ok"]),
            "post_id": post.id,
            "title": post.title,
            "domain": post.domain,
            "reasons": report["reasons"],
            "card_path": card_path,
        }

    def stage_next(self, pipeline: Any, enforce: bool = True, render_card: bool = True) -> Dict[str, Any]:
        """Готовит следующий `ready`-пост (лонгрид + паспорт + карточка + приёмка)."""
        post: Optional[Post] = pipeline.choose_next()
        if post is None:
            return {"ok": False, "error": "нет ready-постов"}
        result = self._stage_post(post, enforce=enforce, render_card=render_card)
        try:
            self.storage.kv_set("staged_next_post_id", post.id)
        except Exception:
            pass
        return result

    def stage_buffer(self, pipeline: Any, count: int = 3, render_card: bool = True) -> Dict[str, Any]:
        """N+3 warm staging: готовит несколько следующих постов, не публикуя их."""
        from .curriculum import open_posts, order_posts, published_ids

        limit = max(1, int(count))
        ready = self.storage.list_posts(status="ready", limit=300, order="created_at ASC")
        published = published_ids(self.storage)
        allowed = open_posts(ready, published)
        candidates = order_posts(allowed or ready)
        if not candidates:
            return {"ok": False, "error": "нет ready-постов", "staged": [], "results": []}
        results = []
        staged_ids = []
        for post in candidates[:limit]:
            result = self._stage_post(post, enforce=False, render_card=render_card)
            results.append(result)
            if result.get("ok"):
                staged_ids.append(post.id)
        try:
            self.storage.kv_set("staged_buffer", json.dumps(staged_ids, ensure_ascii=False))
            if staged_ids:
                self.storage.kv_set("staged_next_post_id", staged_ids[0])
        except Exception:
            pass
        return {
            "ok": bool(staged_ids),
            "staged": staged_ids,
            "results": results,
            "count": len(staged_ids),
        }



