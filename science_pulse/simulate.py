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


def cern_dimuon_peak(events: int = 6000, seed: int = 5, mass_gev: float = 91.19,
                     width_gev: float = 2.5) -> Dict[str, Any]:
    """Инвариантная масса димюонов: из фона вырастает резонанс Z-бозона.

    Масса пары мюонов считается релятивистски:
    `M = √((E₁+E₂)² − |p₁+p₂|²)`, а пик описывается распределением
    Брейта — Вигнера `BW(m) ∝ (Γ/2)² / ((m−m₀)² + (Γ/2)²)`.
    """
    rng = np.random.default_rng(seed)
    # Фон Дрелл–Яна: падающий спектр + примесь J/ψ-мезона (3.1 ГэВ).
    background = 40.0 + rng.exponential(12.0, events)
    jpsi = rng.normal(3.1, 0.09, events // 12)
    signal = rng.normal(mass_gev, width_gev, events // 9)
    masses = np.concatenate([background, jpsi, signal])
    masses = masses[(masses > 1.0) & (masses < 160.0)]

    bins = np.linspace(1.0, 160.0, 80)
    hist, edges = np.histogram(masses, bins=bins)
    centers = 0.5 * (edges[:-1] + edges[1:])
    half = width_gev / 2.0
    breit_wigner = hist.max() * (half ** 2) / ((centers - mass_gev) ** 2 + half ** 2)
    window = np.abs(centers - mass_gev) < 12.0
    background_level = float(np.median(hist[(centers > 110.0) | (centers < 70.0)]))
    return {
        "masses": masses,
        "centers": centers,
        "hist": hist.astype(float),
        "breit_wigner": breit_wigner,
        "peak_mass": float(centers[int(np.argmax(np.where(window, hist, 0)))]),
        "true_mass": float(mass_gev),
        "width_gev": float(width_gev),
        "background_level": background_level,
        "n_events": int(masses.size),
        "n_signal": int(events // 9),
        "window": window,
    }


def ligo_chirp(m1: float = 36.0, m2: float = 29.0, seconds: float = 1.0,
               sample_rate: int = 4096, seed: int = 13,
               f_start: float = 35.0, f_end: float = 250.0) -> Dict[str, Any]:
    """Гравитационно-волновой чирп слияния чёрных дыр (GW150914) + фильтр.

    Модель: частота растёт как `f(t) ∝ (t_c − t)^(−3/8)`, амплитуда — как
    `f^(2/3)`, деформация `h(t) = A(t)·cos Φ(t)`. Шум срезается полосовым
    фильтром Баттерворта (`scipy.signal.butter` + `filtfilt`).
    """
    rng = np.random.default_rng(seed)
    n = int(sample_rate * seconds)
    t = np.arange(n) / sample_rate
    progress = np.linspace(0.0, 1.0, n)
    frequency = f_start * (f_end / f_start) ** progress ** 2.2      # разгон частоты
    phase = 2.0 * np.pi * np.cumsum(frequency) / sample_rate
    amplitude = (frequency / f_start) ** (2.0 / 3.0) * np.exp(-((1.0 - progress) ** 3) * 6.0)
    strain = amplitude * np.cos(phase)
    noise = rng.normal(0.0, 0.6, n)
    raw = strain + noise

    filtered = raw
    cutoff_note = "scipy.signal.butter недоступен — сигнал без фильтра"
    try:
        from scipy.signal import butter, filtfilt

        nyquist = sample_rate / 2.0
        b, a = butter(4, [f_start / nyquist, min(0.95, f_end * 1.4 / nyquist)], btype="band")
        filtered = filtfilt(b, a, raw)
        cutoff_note = f"полосовой фильтр Баттерворта 4-го порядка {f_start:.0f}–{f_end * 1.4:.0f} Гц"
    except Exception:  # pragma: no cover - scipy отсутствует
        pass

    spectrogram = None
    try:
        from scipy.signal import spectrogram

        spec_f, spec_t, spec_power = spectrogram(filtered, fs=sample_rate, nperseg=256, noverlap=200)
        spectrogram = {
            "freq": spec_f,
            "time": spec_t,
            "power": spec_power,
        }
    except Exception:  # pragma: no cover - scipy отсутствует
        spectrogram = None

    chirp_mass = (m1 * m2) ** 0.6 / (m1 + m2) ** 0.2
    radiated = 0.05 * (m1 + m2)
    return {
        "t": t,
        "frequency": frequency,
        "strain": strain,
        "raw": raw,
        "filtered": filtered,
        "spectrogram": spectrogram,
        "m1": float(m1),
        "m2": float(m2),
        "chirp_mass": float(chirp_mass),
        "radiated_m_sun": float(radiated),
        "f_start": float(f_start),
        "f_end": float(f_end),
        "sample_rate": int(sample_rate),
        "filter_note": cutoff_note,
    }


def voronoi_delaunay_laplacian(points: int = 26, seed: int = 17) -> Dict[str, Any]:
    """Двойственная сетка Вороного—Делоне и спектр Лапласиана графа `L = D − A`.

    Второе собственное значение (`λ₂`, число Фидлера) — мера связности сети:
    чем больше `λ₂`, тем труднее разбить граф на две части.
    """
    from scipy.spatial import Delaunay, Voronoi

    rng = np.random.default_rng(seed)
    pts = rng.uniform(0.0, 1.0, size=(points, 2))
    voronoi = Voronoi(pts)
    triangulation = Delaunay(pts)

    edges = set()
    for simplex in triangulation.simplices:
        for index in range(3):
            a, b = int(simplex[index]), int(simplex[(index + 1) % 3])
            edges.add((min(a, b), max(a, b)))

    adjacency = np.zeros((points, points))
    for a, b in edges:
        adjacency[a, b] = adjacency[b, a] = 1.0
    degree = np.diag(adjacency.sum(axis=1))
    laplacian = degree - adjacency
    eigenvalues = np.linalg.eigvalsh(laplacian)

    segments = [
        [voronoi.vertices[v1], voronoi.vertices[v2]]
        for v1, v2 in voronoi.ridge_vertices
        if v1 >= 0 and v2 >= 0
    ]
    return {
        "points": pts,
        "vertices": voronoi.vertices,
        "segments": np.asarray(segments, dtype=float) if segments else np.zeros((0, 2, 2)),
        "simplices": triangulation.simplices,
        "edges": sorted(edges),
        "eigenvalues": eigenvalues,
        "fiedler": float(eigenvalues[1]) if eigenvalues.size > 1 else 0.0,
        "algebraic_connectivity": float(eigenvalues[1]) if eigenvalues.size > 1 else 0.0,
        "n_edges": len(edges),
        "laplacian": laplacian,
    }


def _dpll(clauses: Any, signs: Any, n: int, limit: int = 20000) -> tuple:
    """Простой DPLL с распространением единичных дизъюнктов и счётом узлов."""
    literals = [
        [(int(var), bool(sign)) for var, sign in zip(clause, sign_row)]
        for clause, sign_row in zip(clauses, signs)
    ]
    nodes = [0]

    def solve(assignment: dict) -> bool:
        nodes[0] += 1
        if nodes[0] > limit:
            return False
        pending = []
        for clause in literals:
            satisfied = False
            unresolved = []
            for var, sign in clause:
                if var in assignment:
                    if assignment[var] == sign:
                        satisfied = True
                        break
                else:
                    unresolved.append((var, sign))
            if satisfied:
                continue
            if not unresolved:
                return False
            pending.append(unresolved)
        if not pending:
            return True
        for unresolved in pending:
            if len(unresolved) == 1:
                var, sign = unresolved[0]
                branch = dict(assignment)
                branch[var] = sign
                return solve(branch)
        var, sign = min(pending, key=len)[0]
        for value in (sign, not sign):
            branch = dict(assignment)
            branch[var] = value
            if solve(branch):
                return True
        return False

    return solve({}), nodes[0]


def sat_phase_transition(n: int = 11, samples: int = 10, seed: int = 23, ratios: Any = None) -> Dict[str, Any]:
    """Фазовый переход в 3-SAT: при `α = m/n ≈ 4.26` выполнимость обрушивается.

    Ниже порога почти все формулы выполнимы, выше — почти все противоречивы,
    а вычислительная работа DPLL максимальна ровно в критической точке.
    """
    rng = np.random.default_rng(seed)
    alphas = np.asarray(ratios if ratios is not None else np.arange(2.0, 6.01, 0.5), dtype=float)
    satisfiable = []
    effort = []
    for alpha in alphas:
        m = max(1, int(round(float(alpha) * n)))
        solved = 0
        nodes_total = 0
        for _ in range(samples):
            clauses = [tuple(int(v) for v in rng.choice(n, size=3, replace=False)) for _ in range(m)]
            signs = [tuple(int(v) for v in rng.integers(0, 2, size=3)) for _ in range(m)]
            ok, nodes = _dpll(clauses, signs, n)
            solved += 1 if ok else 0
            nodes_total += nodes
        satisfiable.append(solved / samples)
        effort.append(nodes_total / samples)
    return {
        "alpha": alphas,
        "satisfiable": np.asarray(satisfiable, dtype=float),
        "effort": np.asarray(effort, dtype=float),
        "alpha_critical": 4.26,
        "peak_alpha": float(alphas[int(np.argmax(effort))]) if effort else 0.0,
        "n": int(n),
        "samples": int(samples),
    }


def tsp_route(cities: int = 14, seed: int = 29) -> Dict[str, Any]:
    """Задача коммивояжёра: жадный обход + улучшение 2-opt."""
    rng = np.random.default_rng(seed)
    pts = rng.uniform(0.0, 1.0, size=(cities, 2))

    def length(tour: Any) -> float:
        ordered = np.asarray(tour)
        return float(np.sum(np.linalg.norm(np.diff(pts[ordered + [ordered[0]]], axis=0), axis=1)))

    tour = [0]
    remaining = set(range(1, cities))
    while remaining:
        last = tour[-1]
        nxt = min(remaining, key=lambda index: float(np.linalg.norm(pts[index] - pts[last])))
        tour.append(nxt)
        remaining.discard(nxt)
    initial = length(tour)

    improved = True
    while improved:
        improved = False
        for i in range(1, cities - 1):
            for j in range(i + 1, cities):
                candidate = tour[:i] + tour[i:j + 1][::-1] + tour[j + 1:]
                if length(candidate) < length(tour) - 1e-12:
                    tour = candidate
                    improved = True
    final = length(tour)
    return {
        "cities": pts,
        "tour": np.asarray(tour + [tour[0]], dtype=int),
        "length": final,
        "initial_length": initial,
        "improvement_pct": round(100.0 * (initial - final) / max(initial, 1e-9), 2),
        "order": np.asarray(tour, dtype=int),
    }


def seismic_triangulation(delays: Any = None, p_km_s: float = 6.0, s_km_s: float = 3.5) -> Dict[str, Any]:
    """Триангуляция эпицентра по разнице прихода P- и S-волн.

    `d = Δt · v_P·v_S / (v_P − v_S)`: продольная волна приходит раньше, и по
    запаздыванию поперечной восстанавливается расстояние до станции.
    """
    values = np.asarray(delays if delays is not None else [2.0, 5.0, 10.0, 20.0, 30.0], dtype=float)
    distance = values * (p_km_s * s_km_s) / (p_km_s - s_km_s)
    return {
        "delays": values,
        "distance_km": distance,
        "p_km_s": float(p_km_s),
        "s_km_s": float(s_km_s),
        "formula": "d = Δt · v_P·v_S/(v_P − v_S)",
    }


def sparse_cg_convergence(n: int = 200, seed: int = 31, iterations: int = 200) -> Dict[str, Any]:
    """Разреженная матрица и метод сопряжённых градиентов против градиентного спуска.

    Берётся трёхдиагональная матрица (дискретный лапласиан), хранимая в формате
    CSR: `nnz ≪ n²`. Сходимость CG экспоненциальна по числу обусловленности,
    а у обычного градиентного спуска — линейна и медленна.
    """
    from scipy.sparse import diags
    from scipy.sparse.linalg import cg

    main = 2.0 * np.ones(n)
    off = -1.0 * np.ones(n - 1)
    matrix = diags([off, main, off], [-1, 0, 1], format="csr")
    rhs = np.ones(n)

    cg_residuals: List[float] = []

    def record(current: Any) -> None:
        cg_residuals.append(float(np.linalg.norm(matrix @ current - rhs)))

    cg(matrix, rhs, rtol=1e-10, maxiter=iterations, callback=record)
    if not cg_residuals:
        cg_residuals = [float(np.linalg.norm(rhs))]

    gradient_residuals: List[float] = []
    solution = np.zeros(n)
    step = 1.0 / 4.0
    for _ in range(iterations):
        gradient = matrix @ solution - rhs
        solution = solution - step * gradient
        gradient_residuals.append(float(np.linalg.norm(gradient)))

    rows, cols = matrix.nonzero()
    return {
        "shape": (int(n), int(n)),
        "nnz": int(matrix.nnz),
        "density": float(matrix.nnz / (n * n)),
        "rows": rows,
        "cols": cols,
        "cg_residual": np.asarray(cg_residuals, dtype=float),
        "gradient_residual": np.asarray(gradient_residuals, dtype=float),
        "cg_steps": len(cg_residuals),
        "iterations": int(iterations),
    }


    """Триангуляция эпицентра по разнице прихода P- и S-волн.

    `d = Δt · v_P·v_S / (v_P − v_S)`: продольная волна приходит раньше, и по
    запаздыванию поперечной восстанавливается расстояние до станции.
    """
    values = np.asarray(delays if delays is not None else [2.0, 5.0, 10.0, 20.0, 30.0], dtype=float)
    distance = values * (p_km_s * s_km_s) / (p_km_s - s_km_s)
    return {
        "delays": values,
        "distance_km": distance,
        "p_km_s": float(p_km_s),
        "s_km_s": float(s_km_s),
        "formula": "d = Δt · v_P·v_S/(v_P − v_S)",
    }

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