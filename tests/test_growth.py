import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.growth import AudienceRegistry, ThreadsGrowthEngine, format_report, utm_url
from science_pulse.models import Post


def make_post():
    return Post(
        id="g1",
        domain="physics",
        title="Почему квантовый осциллятор не замирает",
        hook="Почему даже при нуле кельвинов частица движется?",
        body=(
            "В классической механике частица в потенциале при нулевой температуре "
            "покоилась бы в минимуме. Квантовая механика запрещает точные координату "
            "и импульс одновременно, поэтому основное состояние имеет энергию."
        ),
        formula_latex=r"E_n = \hbar\omega(n+1/2)",
        formula_plain="Eₙ = ℏω(n+1/2)",
        source_name="Stack Exchange",
        source_url="https://physics.stackexchange.com/a/1",
    )


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(raw={"growth": {"threads": {"enabled": True, "max_chars": 480}}})

    def test_utm(self):
        url = utm_url("https://example.org/post/1", content="g1")
        self.assertIn("utm_source=threads", url)
        self.assertIn("utm_content=g1", url)

    def test_threads_chain(self):
        engine = ThreadsGrowthEngine(self.config)
        chain = engine.chain(make_post(), "https://example.org/post/g1", "https://t.me/newmathphys")
        self.assertEqual(len(chain), 2)
        self.assertNotIn("https://", chain[0])
        self.assertIn("https://example.org/post/g1", chain[1])
        self.assertIn("t.me/newmathphys", chain[1])
        self.assertTrue(all(len(item) <= 480 for item in chain))
        self.assertIn("ЯВЛЕНИЕ ДНЯ", chain[0])
        self.assertEqual(chain[0].count("#"), 1)
        self.assertNotIn("#", chain[1])
        self.assertNotIn("https://physics.stackexchange.com", chain[1])
        self.assertIn("Первоисточник:", chain[1])

    def test_audience_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = AudienceRegistry(Path(tmp) / "growth.db")
            target_id = registry.add("telegram", "Наука", "https://t.me/science", "physics", 1000)
            self.assertGreater(target_id, 0)
            self.assertEqual(len(registry.list()), 1)
            self.assertTrue(registry.set_status(target_id, "contacted", "написали"))
            registry.event(target_id, "visit", 1)
            report = registry.report()
            self.assertEqual(report["by_platform"][0]["platform"], "telegram")
            self.assertIn("Аудиторный реестр", format_report(report))


if __name__ == "__main__":
    unittest.main()
