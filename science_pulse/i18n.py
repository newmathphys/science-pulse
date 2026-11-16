"""English edition strings: source-native titles, no machine translation."""
from __future__ import annotations

from typing import Any, Dict

from .models import Post

DOMAIN_EN: Dict[str, str] = {
    "math": "Mathematics",
    "physics": "Physics",
    "cs": "Computer science",
}

STEP_TITLES_EN: Dict[int, str] = {
    1: "Origins: axioms, algorithms and statics",
    2: "Coordinates, analysis and motion",
    3: "Classical fields and analysis",
    4: "Probability, fields and algorithms",
    5: "Computation and quanta",
    6: "Applied giants",
}

# English titles are source-native (written for this edition), not MT output.
EN_TITLES: Dict[str, str] = {
    "pythagoras": "Pythagoras: the metric of Euclidean space",
    "euclid_gcd": "Euclid: the oldest working algorithm",
    "archimedes": "Archimedes: the law of floating bodies",
    "newton_gravity": "Newton: the law of universal gravitation",
    "euler_identity": "Euler: the identity that links five constants",
    "fourier_series": "Fourier: a signal as a sum of harmonics",
    "maxwell": "Maxwell: the equations of the electromagnetic field",
    "turing_machine": "Turing: the machine that defined computation",
    "shannon_entropy": "Shannon: entropy and information",
    "noether_symmetry": "Noether: symmetry and conservation laws",
    "schrodinger": "Schrödinger: the wave equation",
    "insar_ndvi": "Satellite interferometry: InSAR fringes and NDVI",
    "schwarzschild_light": "Schwarzschild: black-hole metric and light bending",
    "quantum_tunneling": "Quantum tunnelling and alpha decay",
    "lj_lorenz": "Lennard-Jones dynamics and the Lorenz attractor",
    "al_khwarizmi": "Al-Khwarizmi: algebra as a science of equations",
    "leibniz_boolean": "Leibniz and Boole: binary code and logic",
    "galileo_fall": "Galileo: free fall and the language of experiment",
    "newton_calculus": "Newton and Leibniz: the derivative",
    "lovelace": "Ada Lovelace: the first algorithm",
    "bernoulli_flow": "Bernoulli: energy conservation in flow",
    "gauss_normal": "Gauss: the normal distribution",
    "hoare_sort": "Hoare: quicksort and divide-and-conquer",
    "boltzmann_entropy": "Boltzmann: entropy as the number of states",
    "riemann_integral": "Riemann: the definite integral",
    "dijkstra_shortest": "Dijkstra: shortest paths",
    "planck_quantum": "Planck: the quantum of action",
    "godel_incompleteness": "Gödel: truth beyond proof",
    "rsa_crypto": "RSA: public-key cryptography",
    "einstein_relativity": "Einstein: relativity of time and mass",
    "trigonometry": "Trigonometry: sine and cosine on the unit circle",
    "logarithm": "Logarithms: multiplication as addition",
    "vectors": "Vectors: direction, length and addition",
    "matrices": "Matrices: linear transformations",
    "binary_memory": "Binary code: numbers as bits",
    "harmonic_oscillator": "The harmonic oscillator",
    "wave_phase": "Wave phase and interference",
    "mcculloch_pitts": "McCulloch and Pitts: the logical neuron",
    "complex_numbers": "Complex numbers: rotation and phase",
    "derivative": "The derivative as a rate of change",
    "number_theory": "Number theory: arithmetic of remainders",
    "probability": "Probability: the language of uncertainty",
    "bayes": "Bayes: updating beliefs",
    "differential_equations": "Differential equations: laws in motion",
    "dimensional_analysis": "Dimensional analysis: guessing a formula",
    "conservation_energy": "Conservation of energy",
    "thermodynamics": "Thermodynamics: the limit of heat engines",
    "electromagnetic_wave": "The electromagnetic wave",
    "quantum_uncertainty": "Quantum uncertainty",
    "gravitational_waves": "Gravitational waves: ripples of spacetime",
    "boolean_logic": "Boolean logic: the algebra of truth",
    "finite_automata": "Finite automata: states and transitions",
    "recursion": "Recursion: a problem defined through itself",
    "hash_table": "Hash tables: lookup in constant time",
    "graph_algorithms": "Graph algorithms: shortest paths",
    "information_theory": "Information theory: the cost of uncertainty",
    "machine_learning": "Machine learning: gradients instead of rules",
    "feedback_control": "Feedback control: steering by error",
    "homeostasis": "Homeostasis: a system that holds itself",
    "hadamard_matrices": "Hadamard matrices: orthogonality at maximum",
    "kalman_filter": "Kalman: the filter that guides Apollo and GPS",
    "a_star": "A*: shortest path with a heuristic",
}


def title_en(post: Post) -> str:
    meta = post.meta or {}
    canon_id = str(meta.get("canon_id") or meta.get("foundation_id") or "")
    return EN_TITLES.get(canon_id, post.title)


def domain_en(post: Post) -> str:
    return DOMAIN_EN.get(str(post.domain or ""), str(post.domain or "").upper())


def summary_en(post: Post) -> str:
    """Short English editorial note; full explanation stays in the Russian source."""
    domain = domain_en(post)
    return (
        f"A foundational {domain.lower()} node in the Science Pulse canon. "
        "The formula, code and visual model are shown below. "
        "The full lecture is available in the Russian original."
    )


def step_title_en(step: Any) -> str:
    try:
        return STEP_TITLES_EN.get(int(step), "Additional")
    except (TypeError, ValueError):
        return "Additional"
