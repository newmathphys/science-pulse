"""Детерминированные научные симуляции (NumPy + SciPy, без сети и без LLM).

Все сложные физические поля для карточек-диптихов и страниц сайта
генерируются математически точно, без гигабайтных сырых архивов:

- `insar_interferogram` — интерферограмма InSAR: фазовые кольца Δφ(x, y);
- `ndvi_map` — синтетические полосы NIR/Red и карта индекса NDVI;
- `schwarzschild_rays` — геодезические лучи света у чёрной дыры
  (численное интегрирование орбитального уравнения u'' + u = 1.5·r_s·u²);
- `tunneling_profiles` — туннелирование волнового пакета сквозь барьер
  (split-step FFT для уравнения Шрёдингера) + коэффициент прохождения T(E);
- `lorenz_attractor` — странный аттрактор Лоренца (RK4);
- `lennard_jones` — потенциал Леннард-Джонса V(r) и сила F(r).

Детерминированность: все случайности — только через `np.random.default_rng(seed)`.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np


def _smooth_noise(rng: Any, size: int, octaves: int = 3) -> np.ndarray:
    """Низкочастотный детерминированный шум: сумма нескольких синусоид."""
    grid = np.linspace(0.0, 2.0 * np.pi, size)
    xx, yy = np.meshgrid(grid, grid)
    field = np.zeros((size, size))
    amplitude = 1.0
    total = 0.0
    for _ in range(octaves):
        fx, fy = (int(v) for v in rng.integers(1, 5, size=2))
        px, py = (float(v) for v in rng.uniform(0.0, 2.0 * np.pi, size=2))
        field += amplitude * np.sin(fx * xx + px) * np.cos(fy * yy + py)
        total += amplitude
        amplitude *= 0.55
    return field / max(total, 1e-9)


def insar_interferogram(size: int = 224, seed: int = 7, wavelength_m: float = 0.0556) -> Dict[str, Any]:
    """Интерферограмма радарной интерферометрии (InSAR), C-диапазон Sentinel-1.

    Модель: подъём вулканического очага + сброс по разлому + атмосферный шум.
    Разность фаз Δφ = 4π·d/λ заворачивается в [-π, π] — фазовые кольца.
    """
    rng = np.random.default_rng(seed)
    axis = np.linspace(-1.0, 1.0, size)
    xx, yy = np.meshgrid(axis, axis)

    uplift = 0.035 * np.exp(-(xx**2 + (yy - 0.15) ** 2) / 0.12)      # очаг подъёма, м
    fault = 0.018 * (xx > 0.25) * (1.0 + 0.3 * np.sin(3.0 * yy))     # сброс по разлому, м
    atmosphere = 0.004 * _smooth_noise(rng, size)                    # турбулентность тропосферы
    displacement = uplift + fault + atmosphere

    phase = 4.0 * np.pi * displacement / wavelength_m
    wrapped = np.angle(np.exp(1j * phase))
    profile = wrapped[size // 2, :].copy()
    return {
        "phase": wrapped,
        "displacement": displacement,
        "profile": profile,
        "axis": axis.copy(),
        "wavelength_m": wavelength_m,
        "extent": (-1.0, 1.0, -1.0, 1.0),
    }


def ndvi_map(size: int = 224, seed: int = 11) -> Dict[str, Any]:
    """Синтетические полосы NIR/Red и карта NDVI = (NIR − Red)/(NIR + Red).

    Ландшафт: растительность (высокий NDVI), вода (отрицательный),
    городская застройка (близкий к нулю).
    """
    rng = np.random.default_rng(seed)
    axis = np.linspace(-1.0, 1.0, size)
    xx, yy = np.meshgrid(axis, axis)
    texture = _smooth_noise(rng, size, octaves=4)

    vegetation = np.clip(0.55 + 0.45 * np.sin(2.2 * xx + 0.6) * np.cos(1.7 * yy) + 0.25 * texture, 0.0, 1.0)
    water = np.exp(-((xx + 0.55) ** 2 + (yy + 0.45) ** 2) / 0.18)     # озеро
    urban = np.exp(-((xx - 0.55) ** 2 + (yy - 0.55) ** 2) / 0.10)     # город

    nir = 0.20 + 0.55 * vegetation + 0.05 * texture - 0.18 * water
    red = 0.12 + 0.32 * (1.0 - vegetation) + 0.04 * texture - 0.10 * water + 0.08 * urban
    denominator = np.where(np.abs(nir + red) < 1e-6, 1e-6, nir + red)
    ndvi = (nir - red) / denominator

    return {
        "ndvi": ndvi,
        "nir": nir,
        "red": red,
        "profile": ndvi[size // 2, :].copy(),
        "axis": axis.copy(),
        "extent": (-1.0, 1.0, -1.0, 1.0),
    }


def schwarzschild_rays(n_rays: int = 9, r_s: float = 1.0) -> List[Dict[str, np.ndarray]]:
    """Геодезические лучи света в метрике Шварцшильда (радиус горизонта r_s).

    Численно интегрируется орбитальное уравнение фотона в полярных координатах
        u''(φ) + u = 1.5 · r_s · u²,   u = 1/r,
    что эквивалентно центральному ускорению a = −1.5·h²·r_s·r/|r|⁵ (G = c = 1).
    Каждый луч — с разным прицельным параметром b: сильное отклонение у горизонта.
    """
    from scipy.integrate import solve_ivp

    rays: List[Dict[str, np.ndarray]] = []
    phi0, phi1 = 0.18, np.pi - 0.18
    span = np.linspace(phi0, phi1, 260)
    for index in range(n_rays):
        b = 2.8 + 0.55 * index  # прицельный параметр > b_crit = 1.5√3·r_s ≈ 2.6·r_s
        # граничные условия прямого луча: u = sin(φ)/b, u' = cos(φ)/b
        y0 = [np.sin(phi0) / b, np.cos(phi0) / b]

        def rhs(phi: float, state: np.ndarray) -> np.ndarray:
            u, du = state
            return np.array([du, 1.5 * r_s * u * u - u])

        sol = solve_ivp(rhs, (phi0, phi1), y0, t_eval=span, rtol=1e-7, atol=1e-9)
        u = np.clip(sol.y[0], 1e-6, 2.0)
        phi = sol.t
        radius = 1.0 / u
        x = -radius * np.cos(phi)  # луч летит слева направо
        y = radius * np.sin(phi)
        rays.append({"phi": phi, "u": u, "x": x, "y": y, "b": np.full_like(x, b)})
    return rays


def tunneling_profiles(
    n: int = 512, steps: int = 900, dt: float = 0.004, e_frac: float = 0.65
) -> Dict[str, Any]:
    """Туннелирование волнового пакета сквозь потенциальный барьер (m = ħ = 1).

    Split-step FFT для уравнения Шрёдингера i·∂ψ/∂t = −½·∂²ψ/∂x² + V(x)·ψ
    плюс аналитический коэффициент прохождения T(E) для прямоугольного барьера:
        T = 1 / (1 + V₀²·sinh²(κa) / (4E(V₀ − E))),  κ = √(2(V₀ − E)).
    """
    axis = np.linspace(-8.0, 8.0, n)
    dx = float(axis[1] - axis[0])
    v0 = 1.0
    barrier = (np.abs(axis) < 0.65).astype(float) * v0

    energy = e_frac * v0
    k0 = np.sqrt(2.0 * energy)
    x0, sigma = -3.2, 0.7
    psi = np.exp(-((axis - x0) ** 2) / (2.0 * sigma**2)) * np.exp(1j * k0 * axis)
    psi = psi / np.sqrt(np.sum(np.abs(psi) ** 2) * dx)

    kinetic = np.exp(-1j * 0.5 * (2.0 * np.pi * np.fft.fftfreq(n, d=dx)) ** 2 * dt)
    potential_half = np.exp(-1j * barrier * 0.5 * dt)

    snapshots = {"before": np.abs(psi) ** 2}
    checkpoint = steps // 2
    for step in range(steps):
        psi = potential_half * psi
        psi = np.fft.ifft(kinetic * np.fft.fft(psi))
        psi = potential_half * psi
        if step == checkpoint:
            snapshots["during"] = np.abs(psi) ** 2
    snapshots["after"] = np.abs(psi) ** 2

    e_grid = np.linspace(0.02, 0.98 * v0, 120)
    kappa = np.sqrt(2.0 * (v0 - e_grid))
    sinh_term = np.sinh(kappa * 1.3) ** 2
    t_curve = 1.0 / (1.0 + v0**2 * sinh_term / (4.0 * e_grid * (v0 - e_grid)))

    return {
        "x": axis,
        "psi2": snapshots,
        "barrier": barrier,
        "energy": energy,
        "T": float(t_curve[np.argmin(np.abs(e_grid - energy))]),
        "e_grid": e_grid,
        "t_curve": t_curve,
    }


def lorenz_attractor(steps: int = 4200, dt: float = 0.006, sigma: float = 10.0, rho: float = 28.0, beta: float = 8.0 / 3.0) -> Dict[str, np.ndarray]:
    """Странный аттрактор Лоренца (RK4): классика теории хаоса и предсказания погоды."""
    state = np.array([1.0, 1.0, 20.0])
    out = np.empty((steps, 3))

    def deriv(s: np.ndarray) -> np.ndarray:
        x, y, z = s
        return np.array([sigma * (y - x), x * (rho - z) - y, x * y - beta * z])

    for step in range(steps):
        out[step] = state
        k1 = deriv(state)
        k2 = deriv(state + 0.5 * dt * k1)
        k3 = deriv(state + 0.5 * dt * k2)
        k4 = deriv(state + dt * k3)
        state = state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

    t = np.arange(steps) * dt
    return {"t": t, "x": out[:, 0], "y": out[:, 1], "z": out[:, 2]}


def lennard_jones(n: int = 400, epsilon: float = 1.0, sigma: float = 1.0) -> Dict[str, np.ndarray]:
    """Потенциал Леннард-Джонса V(r) = 4ε[(σ/r)¹² − (σ/r)⁶] и сила F(r) = −dV/dr.

    Равновесие при r = 2^(1/6)·σ, глубина ямы −ε. Основа молекулярной динамики.
    """
    radius = np.linspace(0.92 * sigma, 3.0 * sigma, n)
    sr6 = (sigma / radius) ** 6
    potential = 4.0 * epsilon * (sr6**2 - sr6)
    force = 4.0 * epsilon * (12.0 * sr6**2 / radius - 6.0 * sr6 / radius)
    return {
        "r": radius,
        "V": potential,
        "F": force,
        "r_min": np.array([2.0 ** (1.0 / 6.0) * sigma]),
        "v_min": np.array([-epsilon]),
    }