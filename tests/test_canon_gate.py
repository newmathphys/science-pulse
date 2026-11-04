import tempfile
import unittest
from pathlib import Path

from science_pulse.canon_gate import CanonGate
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.pipeline import Pipeline
from science_pulse.storage import Storage


def make_post(**fields):
    values = dict(
        id="gate1",
        domain="math",
        title="Теорема Пифагора и метрика",
        hook="Почему формула работает в 3D?",
        body="В прямоугольном треугольнике квадрат гипотенузы равен сумме квадратов катетов. " * 6,
        formula_plain="a^2 + b^2 = c^2",
        source_name="test",
        tier="foundation",
    )
    values.update(fields)
    return Post(**values)


class CanonGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(raw={}, root=self.root)
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.gate = CanonGate(self.storage, self.config)

    def tearDown(self):
        self.temp.cleanup()

    def _card(self, post):
        from science_pulse.cards import render_card

        out = Path(self.config.cards_dir) / f"{post.id}.png"
        card = render_card(post, out_path=out, engine="auto")
        return str(card.path) if card else ""

    def test_autofill_empty_canon_fields(self):
        post = make_post()
        self.storage.add_post(post)
        report = self.gate.verify_and_enforce(post, card_path=self._card(post), caption="Подпись поста")
        self.assertTrue(report["ok"], report["reasons"])
        for key in ("era", "scientist", "modern_application", "formula_vars"):
            self.assertTrue(post.meta.get(key), key)

    def test_rejects_broken_post(self):
        post = make_post(body="Коротко.", formula_plain="a^2 + (b^2")
        self.storage.add_post(post)
        report = self.gate.verify_and_enforce(post, card_path=self._card(post), caption="ок")
        self.assertFalse(report["ok"])
        stored = self.storage.get_post(post.id)
        self.assertEqual(stored.status, "rejected")
        self.assertTrue((stored.meta or {}).get("reject_reasons"))

    def test_physics_requires_formula(self):
        post = make_post(domain="physics", formula_plain="", formula_latex="")
        self.storage.add_post(post)
        report = self.gate.verify_and_enforce(post, card_path=self._card(post), caption="ок")
        self.assertFalse(report["ok"])
        self.assertTrue(any("физики" in reason for reason in report["reasons"]), report["reasons"])

    def test_missing_card_rejected(self):
        post = make_post()
        self.storage.add_post(post)
        report = self.gate.verify_and_enforce(post, card_path="", caption="ок")
        self.assertFalse(report["ok"])
        self.assertTrue(any("карточка не найдена" in reason for reason in report["reasons"]))

    def test_stage_next_sets_kv(self):
        post = make_post()
        self.storage.add_post(post)
        report = self.gate.stage_next(Pipeline(self.config))
        self.assertEqual(self.storage.kv_get("staged_next_post_id", ""), report["post_id"])
        self.assertTrue(report["post_id"])


if __name__ == "__main__":
    unittest.main()
