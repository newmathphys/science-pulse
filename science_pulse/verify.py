"""Единая верификация `cli verify`: инварианты, Lean 4, фаззинг, медиа-smoke.

Один вызов проверяет всё, что защищает контент и состояние:

1. **Инварианты состояния** (INV-1…INV-6) — `science_pulse/invariants.py`;
2. **Формальные доказательства** Lean 4 (включая INV-7: гейт и карантин);
3. **Фаззинг стандартов** — детерминированный генератор «плохих» подписей:
   `check()` и `heal()` не должны падать, а `heal()` — не ухудшать результат;
4. **Медиа-smoke** — синтез звука, сборка микро-видео и рендер карточки.
"""
from __future__ import annotations

import contextlib
import logging
import random
import tempfile
from pathlib import Path
from typing import Any, Dict, List

LOGGER = logging.getLogger(__name__)

FUZZ_ALPHABET = (
    "Теорема Пифагора a² + b² = c² ",
    r"\frac{a}{b} ",
    "$$ E = mc^2 $$ ",
    "**жирный** <b>html</b> ",
    "(незакрытая скобка ",
    "}}} ",
    "🛰🚀ℏ ",
    "f(x) = x^2 + 1 ",
    "Пост #25 в канале ",
    "α β γ ∑ ∫ √ ≈ ",
)


@contextlib.contextmanager
def _offline_translation():
    """Фаззинг герметичен: перевод (сеть) подменяется тождеством.

    ``StandardsChecker.heal()`` при низкой доле кириллицы зовёт
    ``translate_preserving_latex``, а тот — сетевые эшелоны (gtx → MyMemory →
    deep-translator). В фаззинге это делает прогон медленным, недетерминированным
    и зависимым от сети (HTTP 429), поэтому на время фаззинга перевод
    отключается: подпись возвращается как есть — ровно так, как ведёт себя
    ``translate_text`` при недоступности всех провайдеров.
    """
    from . import text as text_module

    original = text_module.translate_preserving_latex
    text_module.translate_preserving_latex = lambda value, target="ru": value
    try:
        yield
    finally:
        text_module.translate_preserving_latex = original


def fuzz_captions(iterations: int = 80, seed: int = 42) -> Dict[str, Any]:
    """Детерминированный фаззинг подписей: чекер не падает, heal не ухудшает.

    Прогон полностью офлайн (см. ``_offline_translation``): результат зависит
    только от ``seed`` и ``iterations``, а не от доступности сети.
    """
    from .standards import StandardsChecker

    rng = random.Random(seed)
    checker = StandardsChecker()
    failures: List[str] = []
    healed = 0
    with _offline_translation():
        for index in range(iterations):
            text = "".join(rng.choice(FUZZ_ALPHABET) for _ in range(rng.randint(1, 14)))
            post = _fuzz_post(index, text)
            try:
                before = checker.check(post, text)
                _post, healed_text, _notes = checker.heal(post, text)
                after = checker.check(post, healed_text)
            except Exception as exc:  # чекер обязан быть тотальным
                failures.append(f"#{index}: {type(exc).__name__}: {exc}")
                continue
            if len(after.violations) > len(before.violations):
                failures.append(f"#{index}: heal ухудшил ({len(before.violations)} → {len(after.violations)})")
            if len(after.violations) < len(before.violations):
                healed += 1
    return {"ok": not failures, "iterations": iterations, "healed": healed, "failures": failures[:5]}


def _fuzz_post(index: int, text: str) -> Any:
    from .models import Post

    return Post(
        id=f"fuzz{index}",
        domain="math",
        title="Фаззинг подписи и стандартов качества",
        hook="Проверка устойчивости чекера",
        body=text,
        formula_latex=r"a^2 + b^2 = c^2",
        source_name="Фаззинг",
    )


def run_verify(pipeline: Any, include_media: bool = True, include_lean: bool = True) -> Dict[str, Any]:
    """Полная верификация: инварианты, Lean, фаззинг, медиа."""
    checks: List[Dict[str, Any]] = []

    from .invariants import InvariantChecker
    from .no_llm import audit_no_llm, format_audit

    no_llm = audit_no_llm()
    checks.append({
        "name": "no_llm",
        "ok": no_llm["ok"],
        "detail": format_audit(no_llm),
    })

    translation_off = not pipeline.config.translate
    checks.append({
        "name": "no_ai_translation",
        "ok": translation_off,
        "detail": "перевод выключен (translate: false)" if translation_off
                  else "SP_TRANSLATE включён: контент идёт через переводчик",
    })

    report = InvariantChecker(pipeline.storage).check()
    checks.append({
        "name": "invariants",
        "ok": report.ok,
        "detail": f"{report.checked} проверок" + ("" if report.ok else f", нарушено {len(report.violations)}"),
    })

    if include_lean:
        from .formal import check_lean

        result = check_lean()
        checks.append({
            "name": "lean",
            "ok": bool(result.ok) if hasattr(result, "ok") else True,
            "detail": str(getattr(result, "detail", "доказательства проверены"))[:120],
        })

    fuzz = fuzz_captions()
    checks.append({
        "name": "fuzz",
        "ok": fuzz["ok"],
        "detail": f"{fuzz['iterations']} подписей, вылечено {fuzz['healed']}"
                  + ("" if fuzz["ok"] else "; " + "; ".join(fuzz["failures"])),
    })

    if include_media:
        checks.append(_media_smoke(pipeline))

    ok = all(item["ok"] for item in checks)
    return {"ok": ok, "checks": checks}


def _media_smoke(pipeline: Any) -> Dict[str, Any]:
    """Smoke-тест медиа: звук, микро-видео (6 кадров), карточка."""
    from .cards import render_card
    from .sound import sonify
    from .sources.history_canon import HistoryCanonSource
    from .video import render_video, video_available

    try:
        post = HistoryCanonSource(pipeline.config).fetch(limit=1, cycle=0)[0]
        with tempfile.TemporaryDirectory(prefix="sp_verify_") as tmp:
            work = Path(tmp)
            wav = sonify(post, work / "sound.wav")
            card = render_card(post, out_path=work / "card.png")
            video_ok = True
            video_note = "видео пропущено (нет ffmpeg)"
            if video_available():
                produced = render_video(post, work / "video.mp4", frames=6)
                video_ok = produced is not None
                video_note = f"видео {produced.name}" if produced else "видео не собралось"
            ok = bool(wav.get("path")) and (card.width, card.height) == (1080, 1080) and video_ok
            return {"name": "media", "ok": ok,
                    "detail": f"звук {wav['seconds']}с · карточка {card.width}×{card.height} · {video_note}"}
    except Exception as exc:
        return {"name": "media", "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:120]}


def format_verify(report: Dict[str, Any]) -> str:
    """Человекочитаемый отчёт верификации."""
    lines = ["🧪 <b>Верификация проекта</b>", ""]
    for item in report.get("checks", []):
        icon = "🟢" if item["ok"] else "🔴"
        lines.append(f"{icon} <b>{item['name']}</b>: {item['detail']}")
    lines.append("")
    lines.append("Итог: " + ("✅ все проверки пройдены" if report.get("ok") else "⛔ есть нарушения"))
    return "\n".join(lines)