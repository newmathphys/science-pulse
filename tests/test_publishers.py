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


class CaptionStyleTests(unittest.TestCase):
    """Стиль mokujiro.com: в публичных подписях нет «маркетинговых» смайликов."""

    MARKETING = "❓🏛💡🧮🔢🔬🧠🔗👇🧭📐⚛️💻🪐🎧📖🏷📜🔊🚀✅⏳🔒🃏📻📈📊"

    def setUp(self):
        self.post = Post(
            id="style1",
            domain="math",
            title="Пифагор: теорема о метрике евклидова пространства",
            hook="Почему формула из VI века до н.э. сегодня работает в GPS и 3D-движках?",
            body=(
                "Теорема Пифагора связывает катеты и гипотенузу прямоугольного треугольника. "
                "Это первый великий инвариант геометрии: длина отрезка не зависит от поворота "
                "системы координат, а обобщение на n измерений задаёт евклидову норму вектора. "
            ) * 2,
            formula_latex="a^2 + b^2 = c^2",
            formula_plain="a² + b² = c²",
            source_name="Евклид",
            source_url="https://ru.wikipedia.org/wiki/Теорема_Пифагора",
            meta={
                "section_num": "1.1",
                "era": "530 г. до н.э. • Античная Греция",
                "scientist": "Пифагор Самосский",
            },
        )

    def test_caption_has_no_marketing_emojis(self):
        caption = build_rich_telegram_caption(self.post, 1024, "https://example.org")
        for emoji in self.MARKETING:
            self.assertNotIn(emoji, caption, f"эмодзи {emoji!r} не должно быть в подписи")

    def test_caption_uses_mokujiro_fields(self):
        caption = build_rich_telegram_caption(self.post, 1024, "https://example.org")
        self.assertIn("§ 1.1 · МАТЕМАТИКА", caption)
        self.assertIn("Инвариант:", caption)
        self.assertIn("Первоисточник:", caption)
        self.assertIn("Тренажёр:", caption)

    def test_caption_chain_links_when_parent_published(self):
        self.post.meta["prereq_links"] = [("§ 1.0 Пифагор", "https://t.me/newmathphys/29")]
        caption = build_rich_telegram_caption(self.post, 1024, "https://example.org")
        self.assertIn("← ", caption)
        self.assertIn("§ 1.0 Пифагор", caption)
        self.assertIn("Тренажёр", caption)

    def test_short_text_and_frame_have_no_emojis(self):
        from science_pulse.publishers.base import build_short_text, formula_frame

        short = build_short_text(self.post, 500, "https://example.org")
        frame = formula_frame(self.post)
        self.assertIn("a² + b² = c²", frame)
        for emoji in self.MARKETING:
            self.assertNotIn(emoji, short, f"эмодзи {emoji!r} не должно быть в коротком тексте")
            self.assertNotIn(emoji, frame, f"эмодзи {emoji!r} не должно быть в рамке формулы")


if __name__ == "__main__":
    unittest.main()
