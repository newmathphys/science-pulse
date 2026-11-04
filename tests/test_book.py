import tempfile
import unittest
from pathlib import Path

from science_pulse.book import BookBuilder, build_typst_source, typst_available
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.storage import Storage


def make_post(post_id, domain="math"):
    return Post(
        id=post_id,
        domain=domain,
        title=f"Пост {post_id}: проверка книги",
        hook="Зачем это нужно?",
        body="Текст научного разбора для книги. Второе предложение для объёма.",
        formula_latex=r"a^2 + b^2 = c^2",
        formula_plain="a² + b² = c²",
        source_name="Тест · Книга",
        meta={"scientist": "Пифагор", "era": "530 до н.э.", "modern_application": "GPS"},
    )


class BookSourceTests(unittest.TestCase):
    def test_source_contains_structure(self):
        posts = [make_post("b1", "math"), make_post("b2", "physics")]
        source = build_typst_source(posts, {}, {}, [("c", "Скорость света", "299792458", "м/с")], "2026-11-03")
        self.assertIn("#outline(", source)
        self.assertIn("= Математика", source)
        self.assertIn("= Физика", source)
        self.assertIn("<p-b1>", source)
        self.assertIn("#link(<p-b2>)", source)
        self.assertIn("Словарь фундаментальных констант", source)
        self.assertIn("Предметный указатель учёных", source)
        self.assertIn("299792458", source)

    def test_source_escapes_typst_markup(self):
        post = make_post("b3")
        post.title = "Опасный #заголовок [со скобками]"
        source = build_typst_source([post], {}, {}, [], "2026-11-03")
        self.assertIn("\\#", source)


class BookBuildTests(unittest.TestCase):
    @unittest.skipUnless(typst_available(), "typst не установлен")
    def test_build_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(raw={}, root=root)
            config.ensure_dirs()
            storage = Storage(config.db_path)
            post = make_post("b4")
            storage.add_post(post)
            storage.mark_published(post.id)
            out = BookBuilder(config, storage).build(out_pdf=root / "book.pdf")
            self.assertTrue(out.exists())
            self.assertEqual(out.read_bytes()[:5], b"%PDF-")
            self.assertGreater(out.stat().st_size, 5_000)


if __name__ == "__main__":
    unittest.main()