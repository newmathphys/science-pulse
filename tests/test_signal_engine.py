import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.signal_engine import (
    FeedbackControllerUOS,
    KalmanFilter,
    NeymanPearsonDetector,
    OrthogonalMultiplexer,
    ShannonTextCompressor,
    SignalVolumeMatcher,
    format_signal_report,
    signal_status,
)
from science_pulse.storage import Storage


def make_post(identifier="p1", domain="math", long=False):
    body = (
        "Теорема связывает катеты и гипотенузу прямоугольного треугольника, "
        "а её доказательство опирается на площади квадратов и понятие подобия. "
        "Формула работает в аналитической геометрии, машинном обучении и графике. "
    )
    if long:
        body = body * 8 + "Интеграл, производная, предел, спектр, матрица, тензор, лагранжиан. " * 4
    return Post(
        id=identifier,
        domain=domain,
        title="Теорема Пифагора и метрика евклидова пространства",
        hook="Почему формула из античности работает в 3D-движках?",
        body=body,
        formula_latex=r"a^2 + b^2 = c^2",
        formula_plain="a² + b² = c²",
        source_name="test",
    )


class SignalEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"signal_engine": {"enabled": True}}, root=Path(self.temp.name))
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_signal_volume_fits_short_post(self):
        volume = SignalVolumeMatcher(self.config).match_volume(make_post(), "telegram")
        self.assertTrue(volume["fits"])
        self.assertLessEqual(volume["ratio"], 1.0)

    def test_signal_volume_overloads_threads(self):
        volume = SignalVolumeMatcher(self.config).match_volume(make_post(long=True), "threads")
        self.assertFalse(volume["fits"])
        self.assertIn(volume["recommended_mode"], {"moku3d", "bookfilm", "cheatsheet_table", "logic_proof"})

    def test_shannon_report_and_compress(self):
        compressor = ShannonTextCompressor()
        text = "Это очень общая вода и пустые слова. " * 10 + "Теорема Пифагора связывает катеты и гипотенузу. " * 4
        report = compressor.entropy_report(text)
        self.assertIn("entropy_bits", report)
        self.assertIn("redundancy", report)
        compressed = compressor.compress(text, max_chars=220)
        self.assertLessEqual(len(compressed), 220)
        self.assertIn("Пифагор", compressed)

    def test_feedback_ros_requeues_after_three_failures(self):
        controller = FeedbackControllerUOS(self.storage, self.config)
        post = make_post()
        self.assertEqual(controller.on_publish(post, False)["action"], "retry")
        self.assertEqual(controller.on_publish(post, False)["action"], "retry")
        self.assertEqual(controller.on_publish(post, False)["action"], "requeue")
        self.assertEqual(controller.on_publish(post, True)["action"], "ok")
        self.assertEqual(controller.status()["failures"], 0)

    def test_feedback_uos_changes_mode(self):
        controller = FeedbackControllerUOS(self.storage, self.config)
        first = controller.on_metrics(100, baseline=100)
        self.assertEqual(first["mode"], "normal")
        low = controller.on_metrics(20, baseline=100)
        self.assertEqual(low["mode"], "cheatsheet_table")

    def test_kalman_and_riccati(self):
        values = [10, 12, 11, 13, 12]
        smoothed = KalmanFilter().smooth(values)
        self.assertEqual(len(smoothed), len(values))
        self.assertLess(smoothed[-1], max(values) + 1)
        self.assertGreater(KalmanFilter.riccati_kappa(0.3, 4.0), 0)

    def test_neyman_pearson_filters_noise(self):
        detector = NeymanPearsonDetector(p_fa=0.05)
        items = [1, 2, 2, 3, 100]
        accepted, report = detector.filter_items(items, lambda value: value)
        self.assertEqual(accepted, [100])
        self.assertTrue(report["accept"])
        self.assertGreater(report["lambda"], 0)

    def test_orthogonal_multiplexer(self):
        multiplexer = OrthogonalMultiplexer(guard_hours=4.0)
        self.assertTrue(multiplexer.validate_schedule(["09:00", "13:00", "17:00", "21:00"])["ok"])
        self.assertFalse(multiplexer.validate_schedule(["09:00", "10:00", "13:00"])["ok"])
        self.assertAlmostEqual(multiplexer.sampling_interval(10.0), 0.05)
        self.assertLess(
            OrthogonalMultiplexer.similarity(make_post("a", "math"), make_post("b", "cs")),
            1.0,
        )

    def test_status_and_report(self):
        status = signal_status(self.storage, self.config)
        self.assertIn("feedback", status)
        self.assertIn("multiplexer", status)
        report = format_signal_report(self.storage, self.config, html=False)
        self.assertIn("СИГНАЛОВ", report)
        self.assertNotIn("<b>", report)


if __name__ == "__main__":
    unittest.main()
