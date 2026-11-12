"""Maturity Score: детерминированный порог зрелости выпуска.

Не LLM и не оценка «качества текста»: только проверяемые артефакты.
100 — всё готово; 85 — сработал fallback audiogram вместо book_film.
"""
from __future__ import annotations

from typing import Any, Dict

WEIGHTS: Dict[str, int] = {
    "standards": 30,
    "card": 20,
    "video": 20,
    "challenge": 15,
    "prereq": 15,
}
VIDEO_WEIGHTS = {"book_film": 20, "audiogram": 5, "none": 0}


def maturity_score(
    *,
    standards_ok: bool,
    card_ok: bool,
    video_engine: str = "none",
    challenge_verified: bool = False,
    prereq_ok: bool = False,
    threshold: int = 100,
) -> Dict[str, Any]:
    video = VIDEO_WEIGHTS.get(str(video_engine or "none"), 0)
    components = {
        "standards": WEIGHTS["standards"] if standards_ok else 0,
        "card": WEIGHTS["card"] if card_ok else 0,
        "video": video,
        "challenge": WEIGHTS["challenge"] if challenge_verified else 0,
        "prereq": WEIGHTS["prereq"] if prereq_ok else 0,
    }
    score = sum(components.values())
    return {
        "score": score,
        "threshold": int(threshold),
        "ok": score >= int(threshold),
        "video_engine": str(video_engine or "none"),
        "components": components,
    }


def format_maturity(report: Dict[str, Any]) -> str:
    report = report or {}
    return (
        f"Maturity {report.get('score', 0)}/{report.get('threshold', 100)} · "
        f"video={report.get('video_engine', 'none')} · "
        f"components={report.get('components', {})}"
    )
