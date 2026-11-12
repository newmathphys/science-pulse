import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.kernel import PHASES, SciencePulseKernel
from science_pulse.sources.history_canon import CANON
from science_pulse.storage import Storage


class StubPipeline:
    """Минимальный стенд вместо полного конвейера (герметичные тесты)."""

    def __init__(self, storage):
        self.storage = storage
        self.site_built = 0

    def choose_next(self, domain=None):
        return self.storage.next_ready(domain)

    def build_site(self):
        self.site_built += 1
        return Path("dist")


class KernelTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(
            raw={
                "data_dir": "data",
                "dist_dir": "dist",
                "low_water": 9,
                "schedule": ["09:00", "13:00", "17:00", "21:00"],
                "voice": {"max_chars": 3000},
            },
            root=Path(self.tmp.name),
        )
        self.storage = Storage(self.config.db_path)
        self.pipeline = StubPipeline(self.storage)
        self.kernel = SciencePulseKernel(self.config, self.storage, self.pipeline)

    def tearDown(self):
        self.tmp.cleanup()


class KernelStatusTests(KernelTestCase):
    def test_status_report_shape(self):
        report = self.kernel.status_report()
        self.assertEqual(report["phases"], list(PHASES))
        self.assertEqual(report["canon"]["canon_total"], len(CANON))
        self.assertEqual(report["syllabus"]["branches"], 45)
        self.assertIn("ready", report["queue"])
        self.assertIn("episodes", report["radio"])
        self.assertTrue(report["invariants"]["ok"])
        self.assertEqual(report["invariants"]["checked"], 7)

    def test_format_status_is_readable(self):
        text = self.kernel.format_status()
        for marker in ("ЯДРО SCIENCE PULSE", "Фаз цикла: 6", "Канон:", "Курс:", "Радио:", "Инварианты"):
            self.assertIn(marker, text)

    def test_current_slot_is_deterministic(self):
        slot = self.kernel.current_slot()
        self.assertIn(slot["slot"], self.config.schedule)
        self.assertEqual(slot, self.kernel.current_slot())
        self.assertIsInstance(slot["epoch_slot"], int)

    def test_schedule_falls_back_to_defaults(self):
        empty = Config(raw={}, root=Path(self.tmp.name))
        kernel = SciencePulseKernel(empty, self.storage, self.pipeline)
        self.assertEqual(len(kernel.schedule()), 4)


class KernelCycleTests(KernelTestCase):
    def test_canon_phase_ensures_all_nodes(self):
        result = self.kernel.phase_canon(expand=False)
        self.assertEqual(result["canon_total"], len(CANON))
        self.assertEqual(result["present"], len(CANON))
        self.assertEqual(result["ensured"], len(CANON))
        self.assertEqual(result["missing"], [])

    def test_expand_syllabus_pumps_course_topics(self):
        result = self.kernel.expand_syllabus(count=4)
        self.assertEqual(result["syllabus_added"], 4)
        self.assertEqual(result["cursor"], 4)
        second = self.kernel.expand_syllabus(count=2)
        self.assertEqual(second["syllabus_added"], 2)
        self.assertEqual(second["cursor"], 6)
        sections = sorted(
            str((post.meta or {}).get("section_num") or "")
            for post in self.storage.list_posts(limit=100)
        )
        self.assertIn("11.1", sections)
        self.assertIn("11.3", sections)
        self.assertIn("12.1", sections)

    def test_selection_builds_longread_and_proof(self):
        self.kernel.phase_canon(expand=False)
        result = self.kernel.phase_selection()
        self.assertIsNotNone(result["chosen"])
        self.assertGreater(result["longread_chars"], 1000)
        self.assertTrue(result["merkle"])

    def test_script_phase_produces_five_blocks(self):
        self.kernel.phase_canon(expand=False)
        result = self.kernel.phase_script(voice=False)
        self.assertGreater(result["script_chars"], 200)
        self.assertGreaterEqual(result["blocks"], 3)
        self.assertEqual(result["voice"], {})

    def test_run_cycle_covers_six_phases(self):
        report = self.kernel.run_cycle(expand=False, rebuild_site=False)
        self.assertEqual(set(report), set(PHASES))
        for name, payload in report.items():
            self.assertTrue(payload["ok"], f"фаза {name}: {payload}")
        self.assertFalse(report["atlas"]["rebuilt"])
        self.assertEqual(report["canon"]["present"], len(CANON))
        self.assertTrue(report["telemetry"]["invariants"]["ok"])

    def test_run_cycle_rebuilds_site_when_asked(self):
        report = self.kernel.run_cycle(expand=False, rebuild_site=True)
        self.assertTrue(report["atlas"]["rebuilt"])
        self.assertEqual(self.pipeline.site_built, 1)
        self.assertIn("episodes", report["atlas"]["radio"])

    def test_phase_errors_are_captured_not_raised(self):
        class Broken:
            def choose_next(self, domain=None):
                raise RuntimeError("поломка")

            def build_site(self):
                raise RuntimeError("поломка")

        kernel = SciencePulseKernel(self.config, self.storage, Broken())
        report = kernel.run_cycle(expand=False)
        self.assertFalse(report["selection"]["ok"])
        self.assertIn("поломка", report["selection"]["error"])
        self.assertFalse(report["atlas"]["ok"])


if __name__ == "__main__":
    unittest.main()
