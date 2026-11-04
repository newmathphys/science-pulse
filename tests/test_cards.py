import tempfile
import unittest
from pathlib import Path

from PIL import Image

from science_pulse.cards import extract_sequence, render_card
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.sources.offline import OfflineBunkerSource


class CardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={}, root=self.root)
        self.config.ensure_dirs()

    def tearDown(self):
        self.temp.cleanup()

    def test_render_offline_card(self):
        post = OfflineBunkerSource(self.config).synthesize(2)
        output = self.root / "card.png"
        artifact = render_card(post, out_path=output)
        self.assertTrue(output.exists())
        self.assertEqual(artifact.width, 1080)
        self.assertEqual(artifact.height, 1080)
        self.assertGreater(len(artifact.data), 10_000)
        with Image.open(output) as image:
            self.assertEqual(image.size, (1080, 1080))
            self.assertEqual(image.mode, "RGB")

    def test_extract_sequence(self):
        post = Post(
            id="seq",
            domain="math",
            title="Последовательность",
            body="Первые члены: 0, 1, 1, 2, 3, 5, 8, 13.",
            formula_plain="a(n)",
            meta={"sequence": [0, 1, 1, 2, 3, 5, 8, 13]},
        )
        self.assertEqual(extract_sequence(post), [0, 1, 1, 2, 3, 5, 8, 13])

    def test_theorem_sheet_renders(self):
        post = Post(
            id="theorem",
            domain="physics",
            title="Закон Архимеда",
            hook="Почему тела плавают?",
            body="На тело в жидкости действует выталкивающая сила, равная весу вытесненной среды.",
            formula_latex=r"F_A = \rho g V",
            formula_plain="F_A = ρ g V",
            source_name="test",
        )
        output = self.root / "theorem.png"
        artifact = render_card(post, out_path=output)
        self.assertTrue(output.exists())
        self.assertGreater(len(artifact.data), 10_000)

    def test_render_code_only_card(self):
        post = Post(
            id="code1",
            domain="cs",
            title="Быстрая сортировка без рекурсии",
            hook="Как избежать переполнения стека?",
            body="Итеративная реализация алгоритма сортировки с явным стеком.",
            code="def quicksort(a):\n    stack=[(0,len(a)-1)]\n    while stack:\n        lo,hi=stack.pop()\n    return a",
            source_name="test",
        )
        output = self.root / "code.png"
        artifact = render_card(post, out_path=output)
        self.assertGreater(len(artifact.data), 10_000)


if __name__ == "__main__":
    unittest.main()
