from __future__ import annotations

import json
import math
import random
import time
from typing import Any, Dict, List, Sequence, Tuple


class SOTAKVExtensions:
    """Алгоритмы «после MVP» поверх таблицы kv — без изменения схемы.

    Совместимо с `Storage.kv_get` / `Storage.kv_set`.
    """

    def __init__(self, storage):
        self.storage = storage

    # ------------------------------------------------------------------
    # 1. Байесовский бандит Томпсона
    # ------------------------------------------------------------------
    def _arms(self, domains: Tuple[str, ...]) -> Dict[str, Dict[str, float]]:
        raw = self.storage.kv_get("bandit_arms", "")
        if raw:
            try:
                arms = json.loads(raw)
                if isinstance(arms, dict):
                    for domain in domains:
                        arms.setdefault(domain, {"a": 2.0, "b": 2.0})
                    return arms
            except ValueError:
                pass
        return {domain: {"a": 2.0, "b": 2.0} for domain in domains}

    def select_domain_thompson(self, domains: Tuple[str, ...] = ("math", "physics", "cs")) -> str:
        arms = self._arms(domains)
        sampled = {
            domain: random.betavariate(max(1e-6, arms[domain]["a"]), max(1e-6, arms[domain]["b"]))
            for domain in domains
            if domain in arms
        }
        if not sampled:
            return domains[0]
        return max(sampled, key=sampled.get)

    def reward_domain(self, domain: str, success: bool = True, decay: float = 0.98) -> None:
        arms = self._arms(("math", "physics", "cs"))
        for item in arms.values():
            item["a"] = max(1.0, round(item["a"] * decay, 4))
            item["b"] = max(1.0, round(item["b"] * decay, 4))
        if domain in arms:
            if success:
                arms[domain]["a"] += 1.0
            else:
                arms[domain]["b"] += 1.0
        self.storage.kv_set("bandit_arms", json.dumps(arms, ensure_ascii=False))

    # ------------------------------------------------------------------
    # 2. Hawkes O(1) по Огате
    # ------------------------------------------------------------------
    def check_hawkes_ready(self, beta_per_hour: float = 0.38, eps: float = 0.45) -> Dict[str, float | bool]:
        raw = self.storage.kv_get("hawkes_state", "")
        state = {"last_ts": 0.0, "last_R": 0.0}
        if raw:
            try:
                loaded = json.loads(raw)
                state.update({key: float(loaded.get(key, 0.0)) for key in ("last_ts", "last_R")})
            except (ValueError, TypeError):
                pass
        now_ts = time.time()
        if state["last_ts"] <= 0:
            return {"ready": True, "residual_wave": 0.0, "hours_since_last": 0.0}
        dt_h = max(0.0, (now_ts - state["last_ts"]) / 3600.0)
        residual = math.exp(-beta_per_hour * dt_h) * state["last_R"]
        wave = round(0.75 * residual, 4)
        return {
            "ready": wave <= eps or dt_h >= 6.0,
            "residual_wave": wave,
            "hours_since_last": round(dt_h, 2),
        }

    def record_hawkes_fire(self, beta_per_hour: float = 0.38) -> None:
        raw = self.storage.kv_get("hawkes_state", "")
        state = {"last_ts": 0.0, "last_R": 0.0}
        if raw:
            try:
                loaded = json.loads(raw)
                state.update({key: float(loaded.get(key, 0.0)) for key in ("last_ts", "last_R")})
            except (ValueError, TypeError):
                pass
        now_ts = time.time()
        if state["last_ts"] <= 0:
            new_r = 1.0
        else:
            dt_h = max(0.0, (now_ts - state["last_ts"]) / 3600.0)
            new_r = math.exp(-beta_per_hour * dt_h) * (1.0 + state["last_R"])
        self.storage.kv_set(
            "hawkes_state",
            json.dumps({"last_ts": now_ts, "last_R": round(new_r, 6)}),
        )

    # ------------------------------------------------------------------
    # 3. FSRS v4.5
    # ------------------------------------------------------------------
    @staticmethod
    def fsrs_retrievability(published_at_ts: float, stability_days: float = 7.0) -> float:
        days = max(0.0, (time.time() - published_at_ts) / 86400.0)
        return round((1.0 + (19.0 / 81.0) * (days / max(0.5, stability_days))) ** -0.5, 4)

    # ------------------------------------------------------------------
    # 4. Диск Пуанкаре
    # ------------------------------------------------------------------
    @staticmethod
    def poincare_xy(index: int, total: int, domain: str) -> Tuple[float, float]:
        angles = {"math": 0.0, "physics": 2.0944, "cs": 4.1888}
        base_theta = angles.get(domain, 0.0)
        norm_rank = 1.0 - (index / max(1, total))
        radius = 0.92 * (1.0 - (norm_rank**0.5))
        theta = base_theta + index * 2.39996
        return round(radius * math.cos(theta), 4), round(radius * math.sin(theta), 4)

    # ------------------------------------------------------------------
    # 5. Хоукс: матрица взаимного возбуждения дисциплин A₃ₓ₃
    # ------------------------------------------------------------------
    @staticmethod
    def hawkes_matrix(alpha0: float = 0.418) -> List[List[float]]:
        """Блочная матрица возбуждения дисциплин (math, physics, cs) · α₀.

        Асимметрия дедукции: математика сильнее возбуждает физику (0.612),
        чем физика математику (0.436) — открытие анализа порождает механику,
        а не наоборот.
        """
        raw = [
            [1.000, 0.436, 0.436],
            [0.612, 1.000, 0.284],
            [0.578, 0.315, 1.000],
        ]
        return [[round(alpha0 * value, 6) for value in row] for row in raw]

    @staticmethod
    def spectral_radius(matrix: Sequence[Sequence[float]]) -> float:
        """Спектральный радиус (максимум |λ|) степенной итерацией."""
        size = len(matrix)
        if size == 0:
            return 0.0
        vector = [1.0 / size] * size
        norm = 0.0
        for _ in range(200):
            product = [sum(matrix[row][col] * vector[col] for col in range(size)) for row in range(size)]
            norm = max(abs(item) for item in product) or 1.0
            vector = [item / norm for item in product]
        return round(norm, 6)

    @classmethod
    def hawkes_subcritical(cls, beta: float = 1.0) -> bool:
        """Устойчивость публикационного контура: ρ(A)/β < 1 (нет спам-шторма)."""
        return cls.spectral_radius(cls.hawkes_matrix()) / max(beta, 1e-9) < 1.0

    # ------------------------------------------------------------------
    # 6. Память: термодинамическая поправка FSRS от кривизны графа
    # ------------------------------------------------------------------
    @staticmethod
    def effective_stability(s_base_days: float, parent_distances: Sequence[float]) -> float:
        """S_eff = S_base · (1 + Σ 1/(1 + d_ℍ)) — связность усиливает след."""
        gain = sum(1.0 / (1.0 + max(0.0, float(distance))) for distance in parent_distances)
        return round(s_base_days * (1.0 + gain), 4)

    @staticmethod
    def review_interval_days(stability_days: float, target: float = 0.90) -> float:
        """Оптимальный квант повторения: Δt = S · ln(1/target)."""
        target = min(max(float(target), 1e-6), 0.999999)
        return round(stability_days * math.log(1.0 / target), 4)


# --- Спиновые блоки Каданова: специализация 4 суточных слотов -----------------

KADANOV_BLOCKS: Tuple[Dict[str, Any], ...] = (
    {"slot": "09:00", "domain": "math", "cognitive_temp": 0.35, "layer": 2,
     "title": "Утренний конденсационный импульс"},
    {"slot": "13:00", "domain": "cs", "cognitive_temp": 0.65, "layer": 3,
     "title": "Дневной кинетический дрейф"},
    {"slot": "17:00", "domain": "physics", "cognitive_temp": 0.80, "layer": 1,
     "title": "Вечерний резонанс полей"},
    {"slot": "21:00", "domain": "", "cognitive_temp": 0.45, "layer": 4,
     "title": "Ночная макроскопическая релаксация"},
)


def kadanov_block(slot: str) -> Dict[str, Any]:
    """Спиновый блок Каданова для слота ``HH:MM`` (по умолчанию — синтез)."""
    for block in KADANOV_BLOCKS:
        if block["slot"] == slot:
            return dict(block)
    return dict(KADANOV_BLOCKS[-1])


def preferred_domain(slot: str) -> str:
    """Дисциплина, приоритетная для слота ('' — междисциплинарный синтез)."""
    return str(kadanov_block(slot).get("domain") or "")


# --- Детерминированный хронометр эпохи ---------------------------------------

EPOCH_START_UTC = "2026-01-01T00:00:00+00:00"
SLOT_SECONDS = 6 * 3600


def epoch_slot_index(now: float | None = None) -> int:
    """Номер слота от начала эпохи проекта: ``(now − epoch) // 6 ч``.

    Позволяет восстановить позицию в расписании даже без базы: скрипт,
    запущенный «в чистом поле», точно знает, какой по счёту слот идёт сейчас.
    """
    import datetime as _dt

    start = _dt.datetime.fromisoformat(EPOCH_START_UTC).timestamp()
    current = time.time() if now is None else float(now)
    return max(0, int((current - start) // SLOT_SECONDS))
