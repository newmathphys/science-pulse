import unittest

import numpy as np

from science_pulse import simulate


class SimulateTests(unittest.TestCase):
    def test_insar_interferogram(self):
        data = simulate.insar_interferogram()
        self.assertEqual(data["phase"].shape, (224, 224))
        self.assertTrue(np.isfinite(data["phase"]).all())
        self.assertLessEqual(float(np.abs(data["phase"]).max()), np.pi + 1e-9)
        self.assertEqual(data["profile"].shape, (224,))

    def test_insar_deterministic(self):
        first = simulate.insar_interferogram(seed=3)
        second = simulate.insar_interferogram(seed=3)
        np.testing.assert_allclose(first["phase"], second["phase"])

    def test_ndvi_map(self):
        data = simulate.ndvi_map()
        self.assertEqual(data["ndvi"].shape, (224, 224))
        self.assertTrue(np.isfinite(data["ndvi"]).all())
        # NDVI по определению в диапазоне [-1, 1]
        self.assertGreaterEqual(float(data["ndvi"].min()), -1.0)
        self.assertLessEqual(float(data["ndvi"].max()), 1.0)

    def test_schwarzschild_rays_escape(self):
        rays = simulate.schwarzschild_rays()
        self.assertEqual(len(rays), 9)
        for ray in rays:
            self.assertTrue(np.isfinite(ray["x"]).all())
            # луч приходит слева и уходит вправо: x монотонно растёт
            self.assertLess(float(ray["x"][0]), float(ray["x"][-1]))

    def test_schwarzschild_deterministic(self):
        first = simulate.schwarzschild_rays(n_rays=3)
        second = simulate.schwarzschild_rays(n_rays=3)
        for a, b in zip(first, second):
            np.testing.assert_allclose(a["x"], b["x"])

    def test_tunneling_profiles(self):
        data = simulate.tunneling_profiles(n=256, steps=200)
        self.assertEqual(set(data["psi2"]), {"before", "during", "after"})
        for snapshot in data["psi2"].values():
            self.assertTrue(np.isfinite(snapshot).all())
            self.assertGreaterEqual(float(snapshot.min()), 0.0)
        self.assertGreater(data["T"], 0.0)
        self.assertLess(data["T"], 1.0)

    def test_lorenz_attractor(self):
        data = simulate.lorenz_attractor(steps=600)
        self.assertEqual(data["x"].shape, (600,))
        for key in ("x", "y", "z"):
            self.assertTrue(np.isfinite(data[key]).all())
        # аттрактор ограничен: значения не улетают в бесконечность
        self.assertLess(float(np.abs(data["z"]).max()), 100.0)

    def test_kotelnikov_sampling(self):
        good = simulate.kotelnikov_sampling(oversample=2.0)
        bad = simulate.kotelnikov_sampling(oversample=0.5)
        self.assertLess(good["max_error"], 0.25)
        self.assertGreater(bad["max_error"], good["max_error"])
        self.assertTrue(bad["aliasing"])

    def test_shannon_capacity(self):
        data = simulate.shannon_capacity(bandwidth_hz=1.0, snr_db=20.0)
        self.assertGreater(data["capacity_at_snr"], 6.0)
        self.assertTrue(np.all(np.diff(data["capacity"]) > 0))

    def test_hamming_7_4(self):
        data = simulate.hamming_7_4()
        self.assertTrue(data["orthogonal"])
        self.assertEqual(data["min_distance"], 3)
        self.assertTrue(data["corrected_ok"])
        self.assertEqual(len(data["codewords"]), 16)

    def test_lennard_jones(self):
        data = simulate.lennard_jones()
        self.assertTrue(np.isfinite(data["V"]).all())
        # минимум потенциала −ε при r = 2^(1/6)·σ
        self.assertAlmostEqual(float(data["V"].min()), -1.0, places=2)
        self.assertAlmostEqual(float(data["r_min"][0]), 2.0 ** (1.0 / 6.0), places=3)


if __name__ == "__main__":
    unittest.main()