import tempfile
import unittest
from pathlib import Path
from unittest import mock

from science_pulse import text as text_module
from science_pulse.config import Config
from science_pulse.pipeline import Pipeline
from science_pulse.verify import fuzz_captions, format_verify, run_verify


class FuzzSuiteTests(unittest.TestCase):
    def test_fuzz_many_iterations(self):
        report = fuzz_captions(iterations=150, seed=7)
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(report["iterations"], 150)

    def test_fuzz_deterministic(self):
        first = fuzz_captions(iterations=30, seed=3)
        second = fuzz_captions(iterations=30, seed=3)
        self.assertEqual(first["healed"], second["healed"])


class FuzzHermeticityTests(unittest.TestCase):
    """Регресс: heal() звал сетевой перевод, из-за чего фаззинг зависал и был
    недетерминированным (HTTP 429 от gtx). Фаззинг обязан быть офлайн."""

    def test_fuzz_never_calls_network_translation(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("фаззинг не должен звать translate_text (сеть)")

        with mock.patch.object(text_module, "translate_text", forbidden):
            report = fuzz_captions(iterations=25, seed=11)
        self.assertTrue(report["ok"], report["failures"])

    def test_fuzz_restores_translation(self):
        original = text_module.translate_preserving_latex
        fuzz_captions(iterations=5, seed=1)
        self.assertIs(text_module.translate_preserving_latex, original)


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.pipeline = Pipeline(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_verify_without_media(self):
        report = run_verify(self.pipeline, include_media=False, include_lean=False)
        names = [item["name"] for item in report["checks"]]
        self.assertIn("invariants", names)
        self.assertIn("fuzz", names)
        self.assertIn("Верификация", format_verify(report))


if __name__ == "__main__":
    unittest.main()