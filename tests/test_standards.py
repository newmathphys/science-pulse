import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import CardArtifact, Post
from science_pulse.standards import (
    Standards,
    StandardsChecker,
    brackets_balanced,
    cyrillic_ratio,
    html_balanced,
)
from science_pulse.storage import Storage
from science_pulse.text import translation_seam_score
from science_pulse.verify import fuzz_captions


def make_post(**fields):
    values = dict(
        id="std1",
        domain="math",
        title="Теорема Пифагора и метрика пространства",
        hook="Почему формула из VI века работает в 3D-движках?",
        body="В прямоугольном треугольнике квадрат гипотенузы равен сумме квадратов катетов. "
             "Это первый инвариант геометрии, он задаёт евклидову норму вектора.",
        formula_latex=r"a^2 + b^2 = c^2",
        source_name="Хроника Науки",
    )
    values.update(fields)
    return Post(**values)


class HelperTests(unittest.TestCase):
    def test_cyrillic_ratio(self):
        self.assertGreater(cyrillic_ratio("Теорема Пифагора"), 0.9)
        self.assertLess(cyrillic_ratio("Pythagorean theorem"), 0.1)

    def test_brackets_balanced(self):
        self.assertTrue(brackets_balanced("f(x) = (a + b)")[0])
        self.assertFalse(brackets_balanced("f(x = 1")[0])
        self.assertFalse(brackets_balanced("цена $5")[0])

    def test_html_balanced(self):
        self.assertTrue(html_balanced("<b>текст</b>")[0])
        self.assertFalse(html_balanced("<b>текст")[0])


class CheckerTests(unittest.TestCase):
    def test_good_caption_passes(self):
        checker = StandardsChecker()
        caption = "📐 МАТЕМАТИКА · Теорема Пифагора\n\n" + "Теорема Пифагора связывает катеты и гипотенузу прямоугольного треугольника. " * 4
        report = checker.check(make_post(), caption)
        self.assertTrue(report.ok, report.violations)
        self.assertGreaterEqual(report.checked, 6)

    def test_raw_latex_violation(self):
        checker = StandardsChecker()
        caption = r"Теорема: \frac{a}{b} = c. " + "Текст для длины описания поста. " * 8
        report = checker.check(make_post(), caption)
        self.assertIn("raw_latex", [v.code for v in report.violations])

    def test_short_caption_violation(self):
        report = StandardsChecker().check(make_post(), "Коротко.")
        self.assertIn("length", [v.code for v in report.violations])

    def test_code_ast_violation(self):
        post = make_post(code="def broken(:\n    pass")
        caption = "Текст описания поста для проверки AST. " * 10
        report = StandardsChecker().check(post, caption)
        self.assertIn("code_ast", [v.code for v in report.violations])

    def test_translation_seam_violation(self):
        caption = "Текст описания поста с незакрытой маской __FORMULA_1__ и пробелом , перед знаком. " * 4
        report = StandardsChecker().check(make_post(), caption)
        self.assertIn("translation_seam", [v.code for v in report.violations])

    def test_translation_seam_score_clean_text(self):
        score, details = translation_seam_score("Теорема Пифагора связывает катеты и гипотенузу.")
        self.assertEqual(score, 0)
        self.assertEqual(details, [])

    def test_card_violation(self):
        card = CardArtifact(path="x.png", data=b"0" * 100, width=100, height=100)
        caption = "Текст описания поста для проверки карточки. " * 10
        report = StandardsChecker().check(make_post(), caption, card)
        self.assertIn("card", [v.code for v in report.violations])

    def test_heal_fixes_latex_and_length(self):
        checker = StandardsChecker()
        caption = r"Формула \frac{a}{b} и текст. " * 3
        _post, healed, notes = checker.heal(make_post(), caption)
        self.assertNotIn("\\frac", healed)
        self.assertTrue(notes)

    def test_enforce_quarantines_bad_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={}, root=Path(tmp))
            config.ensure_dirs()
            storage = Storage(config.db_path)
            post = make_post()
            storage.add_post(post)
            checker = StandardsChecker()
            report, _post, _caption = checker.enforce(post, "Плохо.", None, storage)
            self.assertFalse(report.ok)
            self.assertEqual(storage.get_post(post.id).status, "rejected")
            self.assertGreaterEqual(storage.kv_int("quarantine_count", 0), 1)

    def test_standards_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={}, root=Path(tmp))
            config.ensure_dirs()
            storage = Storage(config.db_path)
            checker = StandardsChecker(Standards(min_letters=321))
            checker.save(storage)
            loaded = StandardsChecker.load(storage)
            self.assertEqual(loaded.standards.min_letters, 321)

    def test_parse_value(self):
        self.assertEqual(Standards.parse_value("min_letters", "240"), 240)
        self.assertEqual(Standards.parse_value("min_cyrillic_ratio", "0.5"), 0.5)
        self.assertTrue(Standards.parse_value("check_code_ast", "true"))


class FuzzTests(unittest.TestCase):
    def test_fuzz_captions_stable(self):
        report = fuzz_captions(iterations=40)
        self.assertTrue(report["ok"], report["failures"])


if __name__ == "__main__":
    unittest.main()