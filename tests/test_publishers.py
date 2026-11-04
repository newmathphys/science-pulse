import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.models import CardArtifact, Post, PublishResult
from science_pulse.publishers import manager as manager_module
from science_pulse.publishers.base import Publisher, PublishContext, build_rich_telegram_caption
from science_pulse.publishers.manager import PublisherManager
from science_pulse.storage import Storage


class FakeTelegram(Publisher):
    name = "telegram"
    calls = []

    def __init__(self, config):
        self.config = config

    def available(self):
        return True

    def publish(self, post, card, context):
        FakeTelegram.calls.append("telegram")
        return PublishResult(platform=self.name, ok=True, external_id="1", meta={"file_id": "FILE123"})


class FakeThreads(Publisher):
    name = "threads"
    last_context = None
    calls = []

    def __init__(self, config):
        self.config = config

    def available(self):
        return True

    def publish(self, post, card, context):
        FakeThreads.calls.append("threads")
        FakeThreads.last_context = context
        return PublishResult(platform=self.name, ok=True, external_id="2")


class PublisherManagerTests(unittest.TestCase):
    def setUp(self):
        FakeTelegram.calls = []
        FakeThreads.calls = []
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(
            raw={
                "data_dir": "data",
                "dist_dir": "dist",
                "platforms": {"telegram": {"enabled": True}, "threads": {"enabled": True}},
                "site_base_url": "https://example.org",
            },
            root=self.root,
        )
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.post = Post(
            id="p1",
            domain="math",
            title="Тестовая тема",
            hook="Крючок",
            body="Длинный текст с формулой $x^2$ для проверки публикации.",
            formula_latex="x^2",
            formula_plain="x^2",
            source_name="test",
        )
        self.card = CardArtifact(path="/tmp/card.png", data=b"png", width=1080, height=1080)
        self.storage.add_post(self.post)

    def tearDown(self):
        self.temp.cleanup()

    def test_telegram_first_and_cdn_context(self):
        with patch.dict(manager_module.PUBLISHER_CLASSES, {"telegram": FakeTelegram, "threads": FakeThreads}, clear=True):
            manager = PublisherManager(self.config, self.storage)
            with patch.dict("os.environ", {"CF_WORKER_URL": "https://worker.example"}, clear=False):
                results = manager.publish(self.post, self.card, site_url="https://example.org")
        self.assertEqual([item.platform for item in results], ["telegram", "threads"])
        self.assertEqual(FakeTelegram.calls + FakeThreads.calls, ["telegram", "threads"])
        self.assertEqual(FakeThreads.last_context.public_card_url, "https://worker.example/tg-cdn/FILE123.png")
        self.assertTrue(self.storage.publication_exists("p1", "telegram"))
        self.assertTrue(self.storage.publication_exists("p1", "threads"))
        self.assertEqual(self.post.card_file_id, "FILE123")
        self.assertEqual(self.storage.get_post("p1").card_file_id, "FILE123")

    def test_idempotent_second_call(self):
        with patch.dict(manager_module.PUBLISHER_CLASSES, {"telegram": FakeTelegram, "threads": FakeThreads}, clear=True):
            manager = PublisherManager(self.config, self.storage)
            manager.publish(self.post, self.card)
            second = manager.publish(self.post, self.card)
        self.assertTrue(all(item.skipped for item in second))
        self.assertEqual(self.storage.get_post("p1").card_file_id, "FILE123")

    def test_rich_caption_has_no_raw_latex(self):
        self.post.title = r"Что такое $\frac{\partial \psi}{\partial t}$?"
        self.post.hook = "Короткий вопрос?"
        self.post.body = (
            "Когда квантовая механика была открыта, физики получили новый язык описания мира. "
            r"Уравнение Шрёдингера $i\hbar\frac{\partial\psi}{\partial t}=\hat H\psi$ "
            "связывает эволюцию состояния с гамильтонианом системы. "
            "Этот язык позволил объяснить спектры атомов и поведение молекул."
        )
        self.post.formula_latex = r"i\hbar\frac{\partial\psi}{\partial t}=\hat H\psi"
        caption = build_rich_telegram_caption(self.post, 1024, "https://example.org")
        self.assertNotIn("$", caption)
        self.assertNotIn("\\frac", caption)
        self.assertGreaterEqual(len(caption), 450)
        self.assertLessEqual(len(caption), 1024)

    def test_unavailable_publisher_skipped(self):
        class NoToken(FakeTelegram):
            def available(self):
                return False

        with patch.dict(manager_module.PUBLISHER_CLASSES, {"telegram": NoToken}, clear=True):
            manager = PublisherManager(self.config, self.storage)
            results = manager.publish(self.post, self.card, targets=["telegram"])
        self.assertTrue(results[0].skipped)


if __name__ == "__main__":
    unittest.main()
