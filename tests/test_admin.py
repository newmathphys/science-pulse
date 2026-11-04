import tempfile
import unittest
from pathlib import Path

from science_pulse.admin import TelegramAdmin
from science_pulse.config import Config
from science_pulse.models import Post, PublishResult
from science_pulse.pipeline import Pipeline
from science_pulse.storage import Storage


class FakeSources:
    sources = {}

    def fetch(self, limit_per_source=2, domains=None, include_offline=True):
        return [
            Post(
                id="m1",
                domain="math",
                title="Тестовая математическая тема",
                hook="Крючок",
                body="Длинный текст с формулой $a^2+b^2=c^2$ и подробным объяснением того, почему это равенство работает.",
                formula_latex="a^2+b^2=c^2",
                formula_plain="a^2+b^2=c^2",
                source_name="fake",
            )
        ]

    def status(self):
        return [{"name": "fake", "open": False, "failures": 0, "tier": "online", "last_ok": None, "last_error": None}]


class FakePublishers:
    def __init__(self, storage):
        self.storage = storage

    def publish(self, item, card, site_url="", public_card_url="", targets=None, video=False):
        result = PublishResult(platform="fake", ok=True, external_id="1")
        self.storage.record_publication(item.id, result)
        return [result]

    def available_platforms(self):
        return ["fake"]

    def status(self):
        return [{"name": "fake", "enabled": True, "available": True}]


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.pipeline = Pipeline(
            self.config,
            self.storage,
            FakeSources(),
            FakePublishers(self.storage),
        )
        self.admin = TelegramAdmin(self.config, self.pipeline, token="token", chat_id="123")

    def tearDown(self):
        self.temp.cleanup()

    def test_help_and_status(self):
        self.assertIn("пульт", self.admin.handle_command("/help", []))
        status = self.admin.handle_command("/status", [])
        self.assertIn("Статус", status)
        self.assertIn("Площадки", status)

    def test_queue_and_next(self):
        self.pipeline.harvest()
        queue = self.admin.handle_command("/queue", [])
        self.assertIn("Очередь", queue)
        next_post = self.admin.handle_command("/next", [])
        self.assertIn("Следующий", next_post)

    def test_pause_resume(self):
        self.assertIn("паузе", self.admin.handle_command("/pause", []))
        self.assertEqual(self.storage.kv_get("paused"), "1")
        self.assertIn("возобновлён", self.admin.handle_command("/resume", []))
        self.assertEqual(self.storage.kv_get("paused"), "0")

    def test_force(self):
        self.pipeline.harvest()
        response = self.admin.handle_command("/force", [])
        self.assertIn("Опубликовано", response)

    def test_harvest_command(self):
        response = self.admin.handle_command("/harvest", ["1"])
        self.assertIn("Добавлено", response)

    def test_add_manual_post(self):
        response = self.admin.handle_command(
            "/add", ["math", "|", "Ручная", "тема", "|", "Достаточно", "длинный", "текст", "для", "проверки.", "|", "$x^2$"]
        )
        self.assertIn("Добавлено", response)
        self.assertEqual(self.storage.count("ready"), 1)

    def test_metrics_command(self):
        response = self.admin.handle_command("/metrics", [])
        self.assertIn("Метрики площадок", response)

    def test_invariants_command(self):
        response = self.admin.handle_command("/invariants", [])
        self.assertIn("Инварианты", response)

    def test_lang_switch_and_platforms(self):
        about_ru = self.admin.handle_command("/about", [])
        self.assertIn("Как работает пульт", about_ru)
        self.assertIn("data/science.db", about_ru)
        self.assertIn("English", self.admin.handle_command("/lang", ["en"]))
        self.assertEqual(self.storage.kv_get("admin_lang"), "en")
        self.assertIn("Platforms", self.admin.handle_command("/platforms", []))
        self.assertIn("Capabilities", self.admin.handle_command("/platform", ["telegram"]))
        self.assertIn("How the pult works", self.admin.handle_command("/about", []))
        self.assertIn("Формат: /lang ru|en", self.admin.handle_command("/lang", ["xx"]))

    def test_pult_html_is_telegram_safe(self):
        # parse_mode=HTML: сырые <...> (напр. «<имя>») ломают отправку сообщения.
        import re

        allowed = re.compile(r"</?(?:b|i|code|pre|a|br|h[1-6])\b[^>]*>")
        texts = [
            self.admin.handle_command("/help", []),
            self.admin.handle_command("/about", []),
            self.admin.handle_command("/doctor", []),
            self.admin.handle_command("/platforms", []),
            self.admin.handle_command("/platform", ["telegram"]),
            self.admin.handle_command("/lang", []),
        ]
        for text in texts:
            leftover = allowed.sub("", text)
            self.assertNotIn("<", leftover)
            self.assertNotIn(">", leftover)

    def test_doctor_command(self):
        self.pipeline.harvest()
        report = self.admin.handle_command("/doctor", [])
        self.assertIn("Светофор автономности", report)
        self.assertIn("Telegram-канал", report)
        self.assertIn("Запас очереди", report)
        self.assertIn("Расписание", report)
        self.assertIn("Инварианты", report)

    def test_preview_and_skip(self):
        self.pipeline.harvest()
        first = self.pipeline.choose_next()
        self.admin.send_photo = lambda path, caption="": True  # без сети
        preview = self.admin.handle_command("/preview", [])
        self.assertIn("Предпросмотр", preview)
        skipped = self.admin.handle_command("/skip", [])
        self.assertIn("Отложен", skipped)
        self.assertLess(self.storage.get_post(first.id).quality, 0.05)

    def test_trending_and_pick(self):
        from science_pulse.trending import TrendItem, TrendingRadar

        class FakeRadar(TrendingRadar):
            def scan(self, domain=None, top=5, translate=True):
                items = [
                    TrendItem(
                        title="Новая теорема о простых числах близнецах",
                        url="https://example.com/a",
                        source="Hacker News",
                        domain="math",
                        likes=640,
                        comments=185,
                        heat=96.0,
                        relevance=2,
                    )
                ]
                self.save(items)
                return items

        self.admin.radar_factory = lambda config, storage: FakeRadar(config, storage, http_get=lambda url: None)
        report = self.admin.handle_command("/trending", [])
        self.assertIn("ТОП МИРОВЫХ", report)
        self.assertIn("640", report)

        picked = self.admin.handle_command("/pick", ["1"])
        self.assertIn("В очередь", picked)
        self.assertEqual(self.storage.count("ready"), 1)
        self.assertEqual(self.storage.next_ready().quality, 100.0)

        again = self.admin.handle_command("/pick", ["1"])
        self.assertIn("уже в очереди", again)

    def test_pick_now_publishes(self):
        from science_pulse.trending import TrendItem, TrendingRadar

        class FakeRadar(TrendingRadar):
            def scan(self, domain=None, top=5, translate=True):
                items = [
                    TrendItem(
                        title="Квантовая запутанность в чёрных дырах",
                        url="https://example.com/b",
                        source="Hacker News",
                        domain="physics",
                        likes=300,
                        comments=90,
                        heat=70.0,
                        relevance=2,
                    )
                ]
                self.save(items)
                return items

        self.admin.radar_factory = lambda config, storage: FakeRadar(config, storage, http_get=lambda url: None)
        self.admin.handle_command("/trending", [])
        published = self.admin.handle_command("/pick", ["1", "now"])
        self.assertIn("Опубликован", published)
        self.assertEqual(self.storage.count("published"), 1)

    def test_pick_requires_trending_first(self):
        self.assertIn("Формат: /pick", self.admin.handle_command("/pick", []))
        self.assertIn("Сначала /trending", self.admin.handle_command("/pick", ["1"]))


if __name__ == "__main__":
    unittest.main()
