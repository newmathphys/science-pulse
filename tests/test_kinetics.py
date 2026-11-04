import unittest

from science_pulse.sota import KADANOV_BLOCKS, SOTAKVExtensions, kadanov_block, preferred_domain


class HawkesTests(unittest.TestCase):
    def test_matrix_shape_and_asymmetry(self):
        matrix = SOTAKVExtensions.hawkes_matrix()
        self.assertEqual(len(matrix), 3)
        self.assertTrue(all(len(row) == 3 for row in matrix))
        # Математика возбуждает физику сильнее, чем физика математику (дедукция).
        self.assertGreater(matrix[1][0], matrix[0][1])

    def test_spectral_radius_subcritical(self):
        radius = SOTAKVExtensions.spectral_radius(SOTAKVExtensions.hawkes_matrix())
        self.assertLess(radius, 1.0)
        self.assertTrue(SOTAKVExtensions.hawkes_subcritical())


class MemoryTests(unittest.TestCase):
    def test_effective_stability_grows_with_connectivity(self):
        base = SOTAKVExtensions.effective_stability(2.4, [])
        linked = SOTAKVExtensions.effective_stability(2.4, [0.5, 1.0, 2.0])
        self.assertAlmostEqual(base, 2.4, places=6)
        self.assertGreater(linked, base)

    def test_review_interval_matches_formula(self):
        interval = SOTAKVExtensions.review_interval_days(10.0, target=0.90)
        self.assertAlmostEqual(interval, 10.0 * 0.10536, places=3)


class KadanovTests(unittest.TestCase):
    def test_four_slots(self):
        self.assertEqual(len(KADANOV_BLOCKS), 4)
        self.assertEqual([block["slot"] for block in KADANOV_BLOCKS],
                         ["09:00", "13:00", "17:00", "21:00"])

    def test_domain_specialisation(self):
        self.assertEqual(preferred_domain("09:00"), "math")
        self.assertEqual(preferred_domain("13:00"), "cs")
        self.assertEqual(preferred_domain("17:00"), "physics")
        self.assertEqual(preferred_domain("21:00"), "")

    def test_unknown_slot_falls_back_to_synthesis(self):
        self.assertEqual(kadanov_block("03:00")["layer"], 4)


class EpochClockTests(unittest.TestCase):
    def test_slot_index_is_monotone(self):
        from science_pulse.sota import EPOCH_START_UTC, SLOT_SECONDS, epoch_slot_index
        import datetime as dt

        start = dt.datetime.fromisoformat(EPOCH_START_UTC).timestamp()
        self.assertEqual(epoch_slot_index(start), 0)
        self.assertEqual(epoch_slot_index(start + SLOT_SECONDS), 1)
        self.assertEqual(epoch_slot_index(start + SLOT_SECONDS * 5 + 10), 5)
        self.assertEqual(epoch_slot_index(start - 10_000), 0)


if __name__ == "__main__":
    unittest.main()
