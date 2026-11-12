import unittest

from science_pulse.maturity import format_maturity, maturity_score


class MaturityTests(unittest.TestCase):
    def test_book_film_is_100(self):
        report = maturity_score(
            standards_ok=True,
            card_ok=True,
            video_engine="book_film",
            challenge_verified=True,
            prereq_ok=True,
        )
        self.assertEqual(report["score"], 100)
        self.assertTrue(report["ok"])

    def test_audiogram_fallback_is_85(self):
        report = maturity_score(
            standards_ok=True,
            card_ok=True,
            video_engine="audiogram",
            challenge_verified=True,
            prereq_ok=True,
        )
        self.assertEqual(report["score"], 85)
        self.assertFalse(report["ok"])

    def test_missing_challenge_and_prereq(self):
        report = maturity_score(
            standards_ok=True,
            card_ok=True,
            video_engine="book_film",
            challenge_verified=False,
            prereq_ok=False,
        )
        self.assertEqual(report["score"], 70)
        self.assertIn("Maturity", format_maturity(report))


if __name__ == "__main__":
    unittest.main()
