import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.constants import CONSTANTS, constants_used_by, format_value
from science_pulse.pipeline import Pipeline
from science_pulse.preflight import format_preflight, preflight
from science_pulse.sources.history_canon import HistoryCanonSource


class ConstantsTests(unittest.TestCase):
    def test_registry_has_core_constants(self):
        symbols = {item["symbol"] for item in CONSTANTS}
        for symbol in ("c", "G", "hbar", "k_B", "N_A", "e"):
            self.assertIn(symbol, symbols)

    def test_format_value(self):
        text = format_value(299792458.0)
        self.assertTrue(text.startswith("299792458"))
        self.assertNotIn("e+", text)

    def test_constants_used_by(self):
        source = HistoryCanonSource(Config(raw={}))
        maxwell = source.fetch(limit=1, cycle=6)[0]  # Максвелл: c, epsilon_0, mu_0
        usage = constants_used_by([maxwell])
        self.assertIn("c", usage)
        self.assertIn(maxwell.id, [post.id for post in usage["c"]])


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.pipeline = Pipeline(self.config)
        source = HistoryCanonSource(self.config)
        post = source.fetch(limit=1, cycle=0)[0]
        self.pipeline.storage.add_post(post)

    def tearDown(self):
        self.temp.cleanup()

    def test_preflight_reports_checks(self):
        report = preflight(self.pipeline, with_media=False)
        names = [item["name"] for item in report["checks"]]
        self.assertIn("queue", names)
        self.assertIn("card", names)
        self.assertIn("standards", names)
        self.assertIsNotNone(report["post"])

    def test_preflight_with_media(self):
        report = preflight(self.pipeline, with_media=True)
        names = [item["name"] for item in report["checks"]]
        self.assertIn("voice", names)
        self.assertIn("video", names)

    def test_format_preflight(self):
        text = format_preflight(preflight(self.pipeline, with_media=False))
        self.assertIn("Предполётная проверка", text)
        self.assertIn("Итог", text)

    def test_preflight_empty_queue(self):
        empty_config = Config(raw={}, root=Path(self.temp.name) / "empty")
        empty_config.ensure_dirs()
        report = preflight(Pipeline(empty_config), with_media=False)
        self.assertFalse(report["ok"])
        self.assertIsNone(report["post"])


if __name__ == "__main__":
    unittest.main()