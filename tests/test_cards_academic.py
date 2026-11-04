import tempfile
import unittest
from pathlib import Path

from science_pulse.cards import render_card
from science_pulse.cards_academic import ARCHETYPES, pick_visual_type, render_academic_card
from science_pulse.models import Post


def make_post(post_id="acad1", meta=None, **fields):
    allowed = ("title", "hook", "body", "formula_latex", "formula_plain", "code", "domain", "source_name")
    post_fields = {key: fields.pop(key) for key in list(fields) if key in allowed}
    merged = dict(meta or {})
    merged.update(fields)  # простые именованные параметры уходят в meta
    values = dict(
        id=post_id,
        domain="physics",
        title="Спутниковая интерферометрия и математика кадра",
        hook="Как матричная алгебра находит сдвиги земной коры из космоса?",
        body="Достаточно длинный текст научного разбора для валидации качества поста "
             "и книжной вёрстки карточки академической серии. Продолжение текста для объёма.",
        formula_latex=r"NDVI = \frac{NIR - Red}{NIR + Red}",
        source_name="Тест · Книжная серия",
        meta=merged,
    )
    values.update(post_fields)
    return Post(**values)


class AcademicCardTests(unittest.TestCase):
    def test_pick_visual_type_meta_override(self):
        for archetype in ARCHETYPES:
            post = make_post(meta={"visual_type": archetype})
            self.assertEqual(pick_visual_type(post), archetype)

    def test_pick_visual_type_simulation_implies_diptych(self):
        post = make_post(meta={"simulation": "tunneling"})
        self.assertEqual(pick_visual_type(post), "diptych_insar")

    def test_pick_visual_type_default(self):
        self.assertEqual(pick_visual_type(make_post()), "standard_plot")

    def test_pick_visual_type_code(self):
        post = make_post(formula_latex="", formula_plain="", code="def solve():\n    return 42\n")
        post.title = "Алгоритм быстрой сортировки"
        self.assertEqual(pick_visual_type(post), "code_booktabs")

    def test_all_archetypes_render_1080(self):
        cases = {
            "standard_plot": make_post("a1"),
            "diptych_insar": make_post("a2", visual_type="diptych_insar", simulation="insar"),
            "cheatsheet_table": make_post("a3", visual_type="cheatsheet_table"),
            "timeline_evolution": make_post("a4", visual_type="timeline_evolution"),
            "code_booktabs": make_post("a5", visual_type="code_booktabs"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, post in cases.items():
                artifact = render_academic_card(post, Path(tmp) / f"{name}.png")
                self.assertIsNotNone(artifact, name)
                self.assertEqual((artifact.width, artifact.height), (1080, 1080), name)
                self.assertGreater(len(artifact.data), 10_000, name)

    def test_diptych_simulations_render(self):
        for simulation in ("insar", "ndvi", "geodesics", "tunneling", "lorenz", "lj"):
            post = make_post(f"sim_{simulation}", simulation=simulation)
            with tempfile.TemporaryDirectory() as tmp:
                artifact = render_academic_card(post, Path(tmp) / "card.png")
                self.assertIsNotNone(artifact, simulation)

    def test_render_card_auto_uses_academic_for_meta(self):
        post = make_post(meta={"visual_type": "cheatsheet_table"})
        with tempfile.TemporaryDirectory() as tmp:
            artifact = render_card(post, out_path=Path(tmp) / "card.png")
            self.assertEqual((artifact.width, artifact.height), (1080, 1080))

    def test_render_card_engine_academic(self):
        post = make_post()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = render_card(post, out_path=Path(tmp) / "card.png", engine="academic")
            self.assertEqual((artifact.width, artifact.height), (1080, 1080))

    def test_meta_modern_application_visible(self):
        post = make_post(modern_application="Sentinel-1: мониторинг вулканов")
        with tempfile.TemporaryDirectory() as tmp:
            artifact = render_academic_card(post, Path(tmp) / "card.png")
            self.assertIsNotNone(artifact)


if __name__ == "__main__":
    unittest.main()