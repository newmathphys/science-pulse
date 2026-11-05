import math
import re
import tempfile
import unittest
from pathlib import Path

from science_pulse.challenge import (
    build_challenge,
    challenge_line,
    challenge_question,
    challenge_reveal,
    challenge_summary,
)
from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.post_proof import build_post_proof
from science_pulse.publishers.base import build_rich_telegram_caption
from science_pulse.storage import Storage
from science_pulse.voice import build_lecture_script


def make_post(**fields):
    values = dict(
        id="challenge1",
        domain="physics",
        title="Ньютон: закон всемирного тяготения",
        hook="Как одна формула объяснила и падение яблока, и орбиту Луны?",
        body="Два тела притягиваются с силой, обратно пропорциональной квадрату расстояния.",
        formula_latex=r"F = G\frac{m_1 m_2}{r^2}",
        formula_plain="F = G · (m₁ · m₂) / r²",
        source_name="Фундамент Науки",
        meta={
            "section_num": "2.3",
            "foundation_id": "newton_gravity",
            "modern_application": "GPS, орбиты спутников, баллистика",
        },
    )
    values.update(fields)
    return Post(**values)


class GeneratorTests(unittest.TestCase):
    def test_is_deterministic(self):
        post = make_post()
        self.assertEqual(build_challenge(post), build_challenge(post))
        self.assertEqual(challenge_question(post), build_challenge(post)["question"])

    def test_power_law_ratio_is_proved_by_computation(self):
        post = make_post()
        challenge = build_challenge(post)
        self.assertEqual(challenge["kind"], "ratio")
        self.assertIn("r", challenge["question"])
        factor = int(re.search(r"в (\d+) раза", challenge["question"]).group(1))
        times = int(re.search(r"в (\d+) раз", challenge["answer"]).group(1))
        self.assertEqual(times, factor ** 2)
        # Независимая проверка: F(k·r)/F(r) = 1/k², значит сила ослабнет в k² раз.
        self.assertAlmostEqual(
            (1.0 / (3.0 * factor) ** 2) / (1.0 / 3.0 ** 2), 1.0 / times, places=9
        )

    def test_ratio_needs_a_real_power_law(self):
        # Сумма `a² + b²` степенным законом не является — «во сколько раз» запрещено.
        post = make_post(formula_plain="a² + b²", formula_latex="a^2 + b^2", domain="math",
                         meta={"section_num": "1.1"})
        self.assertNotEqual(build_challenge(post)["kind"], "ratio")

    def test_pythagoras_solves_for_hypotenuse(self):
        post = make_post(
            id="pythagoras", domain="math", formula_plain="a² + b² = c²",
            formula_latex="a^2 + b^2 = c^2", hook="Почему?",
            meta={"section_num": "1.1", "foundation_id": "pythagoras"},
        )
        challenge = build_challenge(post)
        self.assertEqual(challenge["kind"], "solve")
        numbers = {
            name: float(value.replace(",", "."))
            for name, value in re.findall(
                r"([a-z]) = (-?\d+(?:[.,]\d+)?)", challenge["question"] + " " + challenge["answer"]
            )
        }
        self.assertTrue({"a", "b", "c"} <= set(numbers))
        self.assertAlmostEqual(numbers["a"] ** 2 + numbers["b"] ** 2, numbers["c"] ** 2, places=6)

    def test_cs_post_gets_step_count(self):
        post = make_post(
            id="euclid_gcd", domain="cs", title="Алгоритм Евклида и сложность O(log n)",
            formula_plain="gcd(a, b) = gcd(b, a mod b) • Time: O(log n)",
            formula_latex="", meta={"section_num": "1.2"},
        )
        challenge = build_challenge(post)
        self.assertIn(challenge["kind"], {"steps", "growth"})
        size = int(re.search(r"в (\d+) раз", challenge["question"]).group(1))
        steps = int(re.search(r"(\d+) шаг", challenge["answer"]).group(1))
        self.assertEqual(steps, math.ceil(math.log2(size)))

    def test_physics_never_gets_algorithm_task(self):
        post = make_post(formula_plain="s(t) = ½·g·t²", formula_latex="", domain="physics",
                         meta={"section_num": "2.4"})
        self.assertNotIn("алгоритм", build_challenge(post)["question"].lower())

    def test_substitute_uses_real_pi(self):
        from science_pulse.challenge import _substitute_challenge

        post = make_post(
            id="gauss_normal", domain="math",
            formula_plain="p(x) = 1/(σ√(2π)) · e^(−(x−μ)²/(2σ²))",
            formula_latex="", meta={"section_num": "4.3"},
        )
        challenge = _substitute_challenge(post, 1234)
        self.assertEqual(challenge["kind"], "substitute")
        point = int(re.search(r"x = (\d+)", challenge["question"]).group(1))
        value = float(
            re.search(r"= (-?\d+(?:[.,]\d+)?)", challenge["answer"]).group(1).replace(",", ".")
        )
        expected = (1 / math.sqrt(2 * math.pi)) * math.exp(-((point - 1) ** 2) / 2)
        self.assertAlmostEqual(value, expected, places=5)

    def test_unparsable_formula_falls_back_to_concept(self):
        post = make_post(formula_plain="iħ·∂Ψ/∂t = ĤΨ", formula_latex="", domain="physics",
                         meta={"section_num": "5.5"})
        challenge = build_challenge(post)
        self.assertEqual(challenge["kind"], "concept")
        self.assertTrue(challenge["question"].endswith("?"))
        self.assertTrue(challenge["answer"])

    def test_every_challenge_has_question_hint_and_answer(self):
        for formula in ("a² + b² = c²", "F = G·m/r²", "E = h·ν", "S = k_B · ln W",
                        "∃ φ: истинно, но недоказуемо"):
            challenge = build_challenge(make_post(formula_plain=formula))
            self.assertTrue(challenge["question"].endswith("?"), formula)
            self.assertTrue(challenge["hint"], formula)
            self.assertTrue(challenge["answer"], formula)


class PresentationTests(unittest.TestCase):
    def test_line_and_reveal(self):
        challenge = build_challenge(make_post())
        line = challenge_line(challenge)
        self.assertIn("Задача.", line)
        self.assertIn("комментариях", line)
        reveal = challenge_reveal(challenge)
        self.assertIn("Ответ:", reveal)
        self.assertIn(challenge["answer"], reveal)
        self.assertIn(challenge["kind"], challenge_summary(challenge))

    def test_proof_carries_challenge(self):
        post = make_post()
        proof = build_post_proof(post)
        self.assertIn("challenge", proof)
        self.assertEqual(proof["challenge"]["kind"], "ratio")
        self.assertEqual(post.meta["challenge"]["answer"], proof["challenge"]["answer"])

    def test_caption_has_challenge_block(self):
        post = make_post()
        build_post_proof(post)
        caption = build_rich_telegram_caption(post, limit=1024, site_url="https://example.org")
        self.assertIn("Задача.", caption)
        self.assertIn("example.org/post/challenge1.html", caption)
        self.assertLessEqual(len(caption), 1024)

    def test_lecture_script_has_task_and_bridge(self):
        script = build_lecture_script(make_post(), max_chars=3000)
        self.assertIn("Задача слушателю", script)
        self.assertIn("Фундаментальный вопрос", script)
        self.assertIn("Применение сегодня", script)

    def test_site_block_reveals_answer(self):
        from science_pulse.site import SiteBuilder

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=Path(tmp))
            storage = Storage(config.db_path)
            builder = SiteBuilder(config, storage)
            html = builder._challenge_html(make_post())
        self.assertIn("Просветительская задача", html)
        self.assertIn("<details", html)
        self.assertIn("Подсказка", html)
        self.assertIn("Ответ:", html)

    def test_longread_mentions_task_and_answer(self):
        from science_pulse.enricher import enrich_post_longread

        text = enrich_post_longread(make_post())
        self.assertIn("Задача для самопроверки", text)
        self.assertIn("Ответ ядра", text)


if __name__ == "__main__":
    unittest.main()
