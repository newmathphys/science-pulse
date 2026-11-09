"""Математический движок передачи сигналов для Science Pulse.

Пять механизмов из учебника «Теория передачи сигналов» (Зюко, Кловский,
Назаров, Финк, 1980), адаптированных под канал «внимание читателя»:

1. ``SignalVolumeMatcher`` — объём сигнала Vc = Tc·Fc·Hc против ёмкости Vk.
2. ``ShannonTextCompressor`` — энтропия, избыточность и отбор информативных
   предложений.
3. ``FeedbackControllerUOS`` — контуры РОС/УОС: повтор после сбоя и адаптация
   подачи по обратной связи.
4. ``NeymanPearsonDetector`` + ``KalmanFilter`` — отсев хайп-шума и очистка
   метрик от случайных всплесков.
5. ``OrthogonalMultiplexer`` — защитные интервалы и ортогональность потоков.

Модуль детерминирован, не ходит в сеть и не зависит от LLM.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Post
from .text import keywords, smart_sentence_truncate, truncate

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "reading_words_per_second": 3.2,
    "formula_penalty_seconds": 1.5,
    "code_line_penalty_seconds": 1.2,
    "min_entropy_bits": 1.8,
    "max_redundancy": 0.92,
    "p_fa": 0.05,
    "guard_hours": 4.0,
    "auto_visual": False,
    "auto_visual_ratio": 1.8,
    "kalman": {"alpha": 0.3, "process_noise": 0.01, "measurement_noise": 0.1},
    "uos": {"drop_ratio": 0.8, "recover_ratio": 1.2, "baseline_alpha": 0.2},
    "channels": {
        "telegram": 8.5,
        "threads": 4.2,
        "bluesky": 2.5,
        "discord": 16.0,
        "mastodon": 4.2,
        "vk": 32.0,
    },
}

# Частотное ядро русского языка: стабильная база для коротких текстов.
# Значения — условные частоты, нормируются при построении модели.
RUSSIAN_FREQ: Dict[str, float] = {
    word: float(max(2, 1200 - index * 13))
    for index, word in enumerate(
        "и в не на я что он с как это а по но из у к за от о для же так "
        "все она они мы вы то его ее их был была были быть есть может можно "
        "при через после до над под между без более менее очень также только "
        "этот эта эти тот та те свой своя свои который которая которые где "
        "когда почему как если чтобы или либо чем тогда теперь уже еще даже "
        "число функция формула система закон энергия сила поле волна "
        "точка прямая плоскость вектор матрица алгоритм задача решение "
        "время пространство движение скорость масса заряд свет атом "
        "теорема доказательство интеграл производная предел ряд сумма "
        "вероятность информация сигнал канал частота спектр".split()
    )
}


def _engine_config(config: Any = None) -> Dict[str, Any]:
    raw = dict((getattr(config, "raw", {}) or {}).get("signal_engine") or {})
    merged = dict(DEFAULT_CONFIG)
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _tokens(text: str) -> List[str]:
    return [token.lower() for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text or "")]


def _sentences(text: str) -> List[str]:
    clean = " ".join((text or "").split())
    if not clean:
        return []
    parts = re.split(r"(?<=[.!?])\s+", clean)
    return [part.strip() for part in parts if part.strip()]


# =====================================================================
# 1. ОБЪЁМ СИГНАЛА И ЁМКОСТЬ КАНАЛА
# =====================================================================
@dataclass
class SignalVolume:
    duration_s: float
    bandwidth: float
    dynamic_range: float
    volume: float
    capacity: float
    fits: bool
    ratio: float
    recommended_mode: str
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "duration_s": round(self.duration_s, 2),
            "bandwidth": round(self.bandwidth, 3),
            "dynamic_range": round(self.dynamic_range, 3),
            "volume": round(self.volume, 3),
            "capacity": round(self.capacity, 3),
            "fits": self.fits,
            "ratio": round(self.ratio, 3),
            "recommended_mode": self.recommended_mode,
            "details": self.details,
        }


class SignalVolumeMatcher:
    """Согласование объёма поста с ёмкостью канала (глава 1 книги)."""

    def __init__(self, config: Any = None):
        self.config = config
        self.settings = _engine_config(config)

    def channel_capacity(self, platform: str = "telegram", rules: Any = None) -> float:
        channels = self.settings.get("channels") or {}
        if platform in channels:
            try:
                return float(channels[platform])
            except (TypeError, ValueError):
                pass
        if rules is not None:
            try:
                chars = int(rules.limit(platform, "max_caption_chars", 1024))
                return max(1.0, chars / 120.0)
            except Exception:
                pass
        return 8.5

    def measure(self, post: Post, platform: str = "telegram", rules: Any = None) -> SignalVolume:
        text = " ".join(part for part in (post.title, post.hook, post.body) if part)
        words = max(1, len(text.split()))
        reading = words / max(0.5, float(self.settings.get("reading_words_per_second", 3.2)))
        formula_count = len(re.findall(r"[=^_\\∫∑√πℏ∇∂]", f"{post.formula_plain} {post.formula_latex}"))
        code_lines = len((post.code or "").splitlines())
        duration = reading + formula_count * float(self.settings.get("formula_penalty_seconds", 1.5))
        duration += code_lines * float(self.settings.get("code_line_penalty_seconds", 1.2))
        chars = max(1, len(text))
        formula_density = 100.0 * formula_count / chars
        term_density = 100.0 * len(re.findall(r"\b[А-Яа-яЁёA-Za-z]{8,}\b", text)) / chars
        code_ratio = min(1.0, code_lines / 12.0)
        bandwidth = 1.0 + 1.2 * min(1.0, formula_density) + 0.6 * min(1.0, term_density) + 0.4 * code_ratio
        visual_bonus = 0.0
        meta = getattr(post, "meta", {}) or {}
        if post.formula_plain or post.formula_latex:
            visual_bonus += 0.25
        if post.code:
            visual_bonus += 0.2
        if meta.get("lab") or meta.get("simulation"):
            visual_bonus += 0.35
        variant = meta.get("design_variant") if isinstance(meta.get("design_variant"), dict) else {}
        if variant.get("theme") in ("moku3d", "bookfilm", "explainer", "3b1b", "blueprint"):
            visual_bonus += 0.25
        dynamic_range = min(2.2, 1.0 + visual_bonus)
        volume = (duration / 10.0) * bandwidth * dynamic_range
        capacity = self.channel_capacity(platform, rules)
        ratio = volume / max(1e-6, capacity)
        fits = ratio <= 1.0
        if fits:
            mode = "text"
        elif post.code:
            mode = "bookfilm"
        elif post.formula_plain or post.formula_latex:
            mode = "bookfilm"
        else:
            mode = "bookfilm"
        return SignalVolume(
            duration_s=duration,
            bandwidth=bandwidth,
            dynamic_range=dynamic_range,
            volume=volume,
            capacity=capacity,
            fits=fits,
            ratio=ratio,
            recommended_mode=mode,
            details={
                "words": words,
                "formula_count": formula_count,
                "code_lines": code_lines,
                "formula_density": round(formula_density, 3),
                "term_density": round(term_density, 3),
                "platform": platform,
            },
        )

    def match_volume(self, post: Post, platform: str = "telegram", rules: Any = None) -> Dict[str, Any]:
        volume = self.measure(post, platform, rules)
        result = volume.as_dict()
        result["exchange"] = (
            "перевести в визуальный режим и сжать текст"
            if not volume.fits
            else "оставить текстовую подачу"
        )
        return result


# =====================================================================
# 2. ШЕННОН: ЭНТРОПИЯ, ИЗБЫТОЧНОСТЬ, СЖАТИЕ
# =====================================================================
@dataclass
class TextModel:
    counts: Dict[str, float]
    total: float
    vocab: int

    def probability(self, word: str) -> float:
        return max(1e-7, self.counts.get(word, 1.0) / max(1.0, self.total))


class ShannonTextCompressor:
    """Оценка информации и отбор предложений без «воды» (глава 2 книги)."""

    def __init__(self, model: Optional[TextModel] = None):
        self.model = model or self.build_model([])

    @classmethod
    def build_model(cls, texts: Iterable[str] = ()) -> TextModel:
        counts = {word: float(value) for word, value in RUSSIAN_FREQ.items()}
        for text in texts:
            for token in _tokens(text):
                counts[token] = counts.get(token, 0.0) + 1.0
        total = sum(counts.values()) or 1.0
        return TextModel(counts=counts, total=total, vocab=max(2, len(counts)))

    def sentence_information(self, sentence: str) -> float:
        tokens = _tokens(sentence)
        if not tokens:
            return 0.0
        return sum(-math.log2(self.model.probability(token)) for token in tokens) / len(tokens)

    def redundancy(self, text: str) -> float:
        tokens = _tokens(text)
        if not tokens:
            return 0.0
        counts: Dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        entropy = 0.0
        for count in counts.values():
            p = count / len(tokens)
            entropy -= p * math.log2(p)
        max_entropy = math.log2(max(2, self.model.vocab))
        return max(0.0, min(1.0, 1.0 - entropy / max_entropy))

    def entropy_report(self, text: str) -> Dict[str, Any]:
        sentences = _sentences(text)
        return {
            "chars": len(text or ""),
            "sentences": len(sentences),
            "entropy_bits": round(statistics.fmean([self.sentence_information(s) for s in sentences]) if sentences else 0.0, 3),
            "redundancy": round(self.redundancy(text), 3),
            "vocab": self.model.vocab,
        }

    def compress(self, text: str, max_chars: int = 620, min_sentences: int = 2) -> str:
        clean = " ".join((text or "").split())
        if len(clean) <= max_chars:
            return clean
        sentences = _sentences(clean)
        if not sentences:
            return smart_sentence_truncate(clean, 120, max_chars)
        scored = [
            (self.sentence_information(sentence), index, sentence)
            for index, sentence in enumerate(sentences)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected: Dict[int, str] = {}
        used = 0
        for score, index, sentence in scored:
            if len(selected) >= min_sentences and used + len(sentence) + 1 > max_chars:
                continue
            selected[index] = sentence
            used += len(sentence) + 1
            if used >= max_chars:
                break
        if not selected:
            return smart_sentence_truncate(clean, 120, max_chars)
        ordered = [selected[index] for index in sorted(selected)]
        result = " ".join(ordered)
        return truncate(result, max_chars, suffix="…")


# =====================================================================
# 3. ОБРАТНАЯ СВЯЗЬ РОС / УОС
# =====================================================================
class FeedbackControllerUOS:
    """РОС: повтор после сбоя. УОС: адаптация подачи по метрикам (глава 5)."""

    KEY = "signal_feedback"

    def __init__(self, storage: Any = None, config: Any = None):
        self.storage = storage
        self.settings = _engine_config(config)
        self.state = self._load()

    def _load(self) -> Dict[str, Any]:
        raw = self.storage.kv_get(self.KEY, "") if self.storage is not None else ""
        default = {
            "failures": 0,
            "last_ok_ts": 0.0,
            "baseline_score": 0.0,
            "last_score": 0.0,
            "mode": "normal",
            "history": [],
        }
        if not raw:
            return default
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                default.update(loaded)
        except ValueError:
            pass
        return default

    def _save(self) -> None:
        if self.storage is not None:
            self.storage.kv_set(self.KEY, json.dumps(self.state, ensure_ascii=False))

    def on_publish(self, post: Post, ok: bool, error: str = "") -> Dict[str, Any]:
        if ok:
            self.state["failures"] = 0
            self.state["last_ok_ts"] = time.time()
            action = "ok"
        else:
            self.state["failures"] = int(self.state.get("failures", 0)) + 1
            action = "requeue" if self.state["failures"] >= 3 else "retry"
        self.state["last_error"] = error[:200]
        self.state["history"] = (self.state.get("history") or [])[-19:] + [
            {"post_id": post.id, "ok": ok, "action": action, "ts": time.time()}
        ]
        self._save()
        return {"action": action, "failures": self.state["failures"]}

    def on_metrics(self, score: float, baseline: Optional[float] = None) -> Dict[str, Any]:
        score = float(score)
        if baseline is None:
            baseline = float(self.state.get("baseline_score") or 0.0)
        if baseline <= 0:
            baseline = score
        ratio = score / max(1e-6, baseline)
        drop = float((self.settings.get("uos") or {}).get("drop_ratio", 0.8))
        recover = float((self.settings.get("uos") or {}).get("recover_ratio", 1.2))
        if ratio < drop:
            mode = "cheatsheet_table"
        elif ratio > recover:
            mode = "normal"
        else:
            mode = self.state.get("mode", "normal")
        alpha = float((self.settings.get("uos") or {}).get("baseline_alpha", 0.2))
        self.state["baseline_score"] = round((1 - alpha) * baseline + alpha * score, 4)
        self.state["last_score"] = round(score, 4)
        self.state["mode"] = mode
        self._save()
        return {"ratio": round(ratio, 3), "mode": mode, "baseline": self.state["baseline_score"]}

    def status(self) -> Dict[str, Any]:
        return dict(self.state)


# =====================================================================
# 4. НЕЙМАН — ПИРСОН И КАЛМАН — БЬЮСИ
# =====================================================================
class NeymanPearsonDetector:
    """Отношение правдоподобия с фиксированной вероятностью ложной тревоги."""

    def __init__(self, p_fa: float = 0.05):
        self.p_fa = max(1e-6, min(0.5, float(p_fa)))

    def threshold_z(self) -> float:
        return statistics.NormalDist().inv_cdf(1.0 - self.p_fa)

    def detect(self, signal: Sequence[float], noise: Sequence[float]) -> Dict[str, Any]:
        signal_values = [float(value) for value in signal if math.isfinite(float(value))]
        noise_values = [float(value) for value in noise if math.isfinite(float(value))]
        if not signal_values or not noise_values:
            return {"accept": False, "lambda": 0.0, "threshold": 0.0, "p_fa": self.p_fa}
        noise_mean = statistics.fmean(noise_values)
        noise_std = statistics.pstdev(noise_values) or 1e-6
        signal_mean = statistics.fmean(signal_values)
        likelihood = (signal_mean - noise_mean) / noise_std
        threshold = self.threshold_z()
        return {
            "accept": likelihood > threshold,
            "lambda": round(likelihood, 3),
            "threshold": round(threshold, 3),
            "p_fa": self.p_fa,
        }

    def filter_items(self, items: Sequence[Any], score: Any) -> Tuple[List[Any], Dict[str, Any]]:
        scored = [(float(score(item)), item) for item in items]
        if not scored:
            return [], {"accept": False, "lambda": 0.0, "threshold": 0.0, "p_fa": self.p_fa}
        values = [value for value, _ in scored]
        mean = statistics.fmean(values)
        std = statistics.pstdev(values) or 1e-6
        threshold = mean + self.threshold_z() * std
        accepted = [item for value, item in scored if value >= threshold]
        report = {
            "accept": bool(accepted),
            "lambda": round((threshold - mean) / std, 3),
            "threshold": round(threshold, 3),
            "p_fa": self.p_fa,
        }
        return accepted, report


class KalmanFilter:
    """Скалярный фильтр Калмана — Бьюси для очистки метрик от шума."""

    def __init__(self, alpha: float = 0.3, process_noise: float = 0.01,
                 measurement_noise: float = 0.1, initial: float = 0.0):
        self.alpha = max(1e-6, float(alpha))
        self.q = max(1e-9, float(process_noise))
        self.r = max(1e-9, float(measurement_noise))
        self.state = float(initial)
        self.variance = 1.0
        self.initialized = False

    def update(self, value: float) -> float:
        value = float(value)
        if not self.initialized:
            self.state = value
            self.initialized = True
            return self.state
        predicted = self.variance + self.q
        gain = predicted / (predicted + self.r)
        self.state += gain * (value - self.state)
        self.variance = (1.0 - gain) * predicted
        return self.state

    def smooth(self, values: Sequence[float]) -> List[float]:
        return [round(self.update(value), 4) for value in values]

    @staticmethod
    def riccati_kappa(alpha: float, lam: float) -> float:
        return float(alpha) * (math.sqrt(1.0 + max(0.0, float(lam))) - 1.0)


# =====================================================================
# 5. ОРТОГОНАЛЬНОЕ РАЗДЕЛЕНИЕ ПОТОКОВ
# =====================================================================
class OrthogonalMultiplexer:
    """Защитные интервалы и ортогональность визуально-акустических базисов."""

    def __init__(self, guard_hours: float = 4.0):
        self.guard_hours = max(0.0, float(guard_hours))

    def guard_ok(self, previous_ts: float, now_ts: Optional[float] = None) -> bool:
        now = time.time() if now_ts is None else float(now_ts)
        return (now - float(previous_ts)) >= self.guard_hours * 3600.0

    def validate_schedule(self, slots: Sequence[str]) -> Dict[str, Any]:
        parsed: List[int] = []
        for slot in slots:
            try:
                hours, minutes = str(slot).split(":", 1)
                parsed.append(int(hours) * 60 + int(minutes))
            except (ValueError, AttributeError):
                continue
        parsed = sorted(set(parsed))
        gaps = [
            (parsed[index + 1] - parsed[index]) / 60.0
            for index in range(len(parsed) - 1)
        ]
        return {
            "slots": len(parsed),
            "gaps_hours": gaps,
            "ok": bool(gaps) and all(gap >= self.guard_hours for gap in gaps),
            "guard_hours": self.guard_hours,
        }

    @staticmethod
    def basis(post: Post) -> Dict[str, Any]:
        meta = getattr(post, "meta", {}) or {}
        variant = meta.get("design_variant") if isinstance(meta.get("design_variant"), dict) else {}
        return {
            "domain": post.domain,
            "theme": str(variant.get("theme") or meta.get("style_variant") or "academic"),
            "color": {"math": "teal", "physics": "blue", "cs": "gold"}.get(post.domain, "ink"),
            "sound": {"math": "fourier", "physics": "packet", "cs": "clicks"}.get(post.domain, "tone"),
        }

    @classmethod
    def similarity(cls, left: Post, right: Post) -> float:
        a, b = cls.basis(left), cls.basis(right)
        score = 0.0
        score += 0.5 if a["domain"] == b["domain"] else 0.0
        score += 0.3 if a["theme"] == b["theme"] else 0.0
        score += 0.2 if a["sound"] == b["sound"] else 0.0
        return round(score, 3)

    @staticmethod
    def sampling_interval(f_max: float) -> float:
        return 1.0 / (2.0 * max(1e-9, float(f_max)))


# =====================================================================
# Отчёты для /doctor и /ab
# =====================================================================
def signal_status(storage: Any = None, config: Any = None) -> Dict[str, Any]:
    settings = _engine_config(config)
    feedback = FeedbackControllerUOS(storage, config).status()
    slots = list((getattr(config, "raw", {}) or {}).get("schedule") or [])
    multiplexer = OrthogonalMultiplexer(float(settings.get("guard_hours", 4.0)))
    return {
        "enabled": bool(settings.get("enabled", True)),
        "feedback": feedback,
        "multiplexer": multiplexer.validate_schedule(slots),
        "p_fa": float(settings.get("p_fa", 0.05)),
        "channels": settings.get("channels", {}),
    }


def format_signal_report(storage: Any = None, config: Any = None, html: bool = True) -> str:
    status = signal_status(storage, config)
    feedback = status["feedback"]
    multiplexer = status["multiplexer"]
    lines = [
        "<b>МАТЕМАТИЧЕСКИЙ ДВИЖОК СИГНАЛОВ</b>" if html else "МАТЕМАТИЧЕСКИЙ ДВИЖОК СИГНАЛОВ",
        f"Состояние: {'включён' if status['enabled'] else 'выключен'}",
        f"УОС: режим {feedback.get('mode', 'normal')} · baseline {feedback.get('baseline_score', 0):.2f}"
        f" · сбоев {feedback.get('failures', 0)}",
        f"Защитные интервалы: {'OK' if multiplexer['ok'] else 'нарушены'}"
        f" · слотов {multiplexer['slots']} · зазор {multiplexer['guard_hours']:.1f} ч",
        f"Нейман—Пирсон: P_лт ≤ {status['p_fa']:.2f}",
    ]
    return "\n".join(lines)
