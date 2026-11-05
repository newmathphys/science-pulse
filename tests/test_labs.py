"""Шесть лабораторных стендов: численные свойства, а не «картинка красивая»."""

import unittest

import numpy as np

from science_pulse import simulate, sound
from science_pulse.cards_academic import SIMULATIONS
from science_pulse.models import Post

NEW_STANDS = ("cern_dimuon", "ligo_chirp", "voronoi_laplacian", "sat_tsp", "sparse_cg", "seismic_ps")


def make_post(identifier: str = "lab1", simulation: str = "") -> Post:
    return Post(
        id=identifier, domain="physics", title="Лабораторный стенд",
        body="Разбор лабораторного стенда для проверки численных свойств модели. " * 3,
        formula_latex="x^2", formula_plain="x²",
        meta={"simulation": simulation, "section_num": "7.1"},
    )


class StandRegistryTests(unittest.TestCase):
    def test_all_stands_registered(self):
        for name in NEW_STANDS:
            self.assertIn(name, SIMULATIONS, name)


class CernDimuonTests(unittest.TestCase):
    def test_peak_found_near_true_mass(self):
        data = simulate.cern_dimuon_peak()
        self.assertLess(abs(data["peak_mass"] - data["true_mass"]), 5.0)
        self.assertGreater(data["n_events"], 1000)

    def test_breit_wigner_maximum_at_resonance(self):
        data = simulate.cern_dimuon_peak()
        self.assertAlmostEqual(float(data["centers"][int(np.argmax(data["breit_wigner"]))]),
                               data["true_mass"], delta=3.0)


class LigoChirpTests(unittest.TestCase):
    def test_frequency_rises_monotonically(self):
        data = simulate.ligo_chirp()
        self.assertTrue(np.all(np.diff(data["frequency"]) > 0))
        self.assertAlmostEqual(data["frequency"][0], data["f_start"], delta=1.0)
        self.assertAlmostEqual(data["frequency"][-1], data["f_end"], delta=5.0)

    def test_bandpass_filter_reduces_noise(self):
        data = simulate.ligo_chirp()
        self.assertLess(float(np.std(data["filtered"])), float(np.std(data["raw"])))
        self.assertIn("Баттерворта", data["filter_note"])

    def test_spectrogram_available(self):
        data = simulate.ligo_chirp()
        self.assertIsNotNone(data["spectrogram"])
        self.assertEqual(len(data["spectrogram"]["freq"]), data["spectrogram"]["power"].shape[0])

    def test_chirp_mass_plausible(self):
        data = simulate.ligo_chirp()
        self.assertTrue(25.0 < data["chirp_mass"] < 31.0)  # 36 + 29 M☉

    def test_audio_chirp_rises(self):
        import tempfile
        import wave
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "chirp.wav"
            sound.sonify(make_post("chirp", "ligo_chirp"), target, seconds=2.0)
            with wave.open(str(target)) as handle:
                frames = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
        rate = sound.SAMPLE_RATE
        head = frames[: rate // 4].astype(float)
        tail = frames[-rate // 4:].astype(float)
        first = float(np.argmax(np.abs(np.fft.rfft(head)))) * rate / len(head)
        last = float(np.argmax(np.abs(np.fft.rfft(tail)))) * rate / len(tail)
        self.assertGreater(last, first, "чирп должен ускорять частоту")


class VoronoiLaplacianTests(unittest.TestCase):
    def test_laplacian_spectrum_and_fiedler(self):
        data = simulate.voronoi_delaunay_laplacian()
        eigenvalues = data["eigenvalues"]
        self.assertAlmostEqual(float(eigenvalues[0]), 0.0, places=6)   # у лапласиана есть нуль
        self.assertGreater(data["fiedler"], 0.0)
        self.assertGreaterEqual(data["n_edges"], len(data["points"]) - 1)
        self.assertGreater(len(data["segments"]), 0)


class SatPhaseTransitionTests(unittest.TestCase):
    def test_satisfiability_collapses_above_threshold(self):
        data = simulate.sat_phase_transition()
        self.assertGreater(float(data["satisfiable"][0]), 0.7)         # ниже порога — выполнимо
        self.assertLess(float(data["satisfiable"][-1]), 0.3)           # выше порога — нет
        self.assertEqual(data["alpha_critical"], 4.26)

    def test_effort_peaks_near_transition(self):
        data = simulate.sat_phase_transition()
        self.assertGreaterEqual(float(data["peak_alpha"]), 4.0)


class TspTests(unittest.TestCase):
    def test_two_opt_improves_tour(self):
        route = simulate.tsp_route()
        self.assertLessEqual(route["length"], route["initial_length"] + 1e-9)
        self.assertGreaterEqual(route["improvement_pct"], 0.0)
        self.assertEqual(sorted(route["order"].tolist()), list(range(len(route["cities"]))))


class SparseCgTests(unittest.TestCase):
    def test_sparsity_and_convergence(self):
        data = simulate.sparse_cg_convergence()
        self.assertLess(data["nnz"], data["shape"][0] ** 2)
        self.assertLess(data["density"], 0.05)
        residual = data["cg_residual"]
        self.assertLess(float(residual[-1]), float(residual[0]) * 1e-6)

    def test_cg_beats_gradient_descent(self):
        data = simulate.sparse_cg_convergence()
        self.assertLess(float(data["cg_residual"][-1]), float(data["gradient_residual"][-1]))


class SeismicTriangulationTests(unittest.TestCase):
    def test_distance_formula(self):
        data = simulate.seismic_triangulation(delays=[10.0])
        self.assertAlmostEqual(float(data["distance_km"][0]), 84.0, delta=0.5)

    def test_monotone_growth(self):
        data = simulate.seismic_triangulation()
        self.assertTrue(np.all(np.diff(data["distance_km"]) > 0))


if __name__ == "__main__":
    unittest.main()
