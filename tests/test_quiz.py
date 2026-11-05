import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from science_pulse.challenge import build_challenge, quiz_options
from science_pulse.config import Config
from science_pulse.kernel import SciencePulseKernel
from science_pulse.models import Post
from science_pulse.publishers.base import formula_frame
from science_pulse.publishers.telegram import TelegramPublisher
from science_pulse.storage import Storage


def make_post(**fields):
    values = dict(
        id="quiz1",
        domain="physics",
        title="Ньютон: закон всемирного тяготения",
        hook="Как одна формула объяснила и падение яблока, и орбиту Луны?",
        body="Сила обратно пропорциональна квадрату расстояния.",
        formula_plain="F = G · (m₁ · m₂) / r²",
        source_name="Фундамент Науки",
        meta={"section_num": "2.3", "foundation_id": "newton_gravity"},
    )
    values.update(fields)
    return Post(**values)


class QuizOptionsTests(unittest.TestCase):
    def test_four_unique_options_with_correct_index(self):
        challenge = build_challenge(make_post())
        quiz = quiz_options(challenge)
        self.assertIsNotNone(quiz)
        self.assertEqual(len(quiz["options"]), 4)
        self.assertEqual(len(set(quiz["options"])), 4)
        correct = quiz["options"][quiz["correct_index"]]
        self.assertIn(challenge["answer"].split(".")[0], correct)
        for option in quiz["options"]:
            self.assertLessEqual(len(option), 100)

    def test_is_deterministic(self):
        self.assertEqual(
            quiz_options(build_challenge(make_post())),
            quiz_options(build_challenge(make_post())),
        )

    def test_concept_challenge_has_no_quiz(self):
        post = make_post(formula_plain="∀ φ: истинно, но недоказуемо", formula_latex="", domain="math")
        challenge = build_challenge(post)
        self.assertEqual(challenge["kind"], "concept")
        self.assertIsNone(quiz_options(challenge))

    def test_cs_steps_quiz(self):
        post = make_post(
            id="euclid_gcd", domain="cs",
            formula_plain="gcd(a, b) = gcd(b, a mod b) • Time: O(log n)",
            meta={"section_num": "1.2"},
        )
        quiz = quiz_options(build_challenge(post))
        self.assertIsNotNone(quiz)
        self.assertIn("шаг", quiz["options"][quiz["correct_index"]])


class FormulaFrameTests(unittest.TestCase):
    def test_frame_is_mobile_readable(self):
        frame = formula_frame(make_post())
        lines = frame.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("┌"))
        self.assertTrue(lines[1].startswith("│ "))
        self.assertTrue(lines[2].startswith("└"))
        self.assertIn("r²", frame)
        self.assertLessEqual(max(len(line) for line in lines), 34)

    def test_no_formula_no_frame(self):
        self.assertEqual(formula_frame(Post(id="x", domain="cs", title="Код")), "")

    def test_long_formula_is_truncated(self):
        post = make_post(formula_plain="∇·E = ρ/ε₀, ∇×B = μ₀J + μ₀ε₀ ∂E/∂t, ∇·B = 0")
        frame = formula_frame(post)
        self.assertLessEqual(len(frame.splitlines()[1]), 34)


class TelegramPollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ, {"TG_BOT_TOKEN": "123:abc", "TG_CHANNEL_ID": "@channel"}, clear=False
        )
        self.env.start()
        self.config = Config(raw={}, root=Path(self.tmp.name))
        self.publisher = TelegramPublisher(self.config)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def _fake_response(payload):
        response = mock.Mock()
        response.json.return_value = payload
        return response

    def test_send_poll_builds_native_quiz(self):
        captured = {}

        def fake_post(url, data=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            return self._fake_response({"ok": True, "result": {"message_id": 42}})

        with mock.patch("science_pulse.publishers.telegram.requests.post", fake_post):
            result = self.publisher.send_poll(make_post(), reply_to=7)
        self.assertEqual(result["message_id"], 42)
        self.assertTrue(captured["url"].endswith("/sendPoll"))
        self.assertEqual(captured["data"]["type"], "quiz")
        self.assertEqual(captured["data"]["reply_to_message_id"], "7")
        options = json.loads(captured["data"]["options"])
        self.assertEqual(len(options), 4)
        self.assertLess(int(captured["data"]["correct_option_id"]), 4)

    def test_send_poll_returns_none_without_number(self):
        with mock.patch("science_pulse.publishers.telegram.requests.post") as fake_post:
            result = self.publisher.send_poll(
                make_post(formula_plain="∀ φ: истинно, но недоказуемо", formula_latex="")
            )
        self.assertIsNone(result)
        fake_post.assert_not_called()

    def test_unavailable_publisher_sends_nothing(self):
        self.env.stop()
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        publisher = TelegramPublisher(Config(raw={}, root=Path(self.tmp.name)))
        with mock.patch("science_pulse.publishers.telegram.requests.post") as fake_post:
            self.assertIsNone(publisher.send_poll(make_post()))
        fake_post.assert_not_called()


class DeepCrawlerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=self.root)
        self.storage = Storage(self.config.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_offline_returns_reason(self):
        class Offline:
            def choose_next(self, domain=None):
                return None

            def build_site(self):
                return Path("dist")

        kernel = SciencePulseKernel(self.config, self.storage, Offline())
        report = kernel.expand_deep(count=3)
        self.assertEqual(report["deep_added"], 0)
        self.assertIn("нет HTTP", report["reason"])

    def test_online_enqueues_discovered_topics(self):
        def fake_get_json(url, timeout=3.0, **kwargs):
            if "cmtype=subcat" in url:
                return {"query": {"categorymembers": [{"title": "Категория:Теория чисел"}]}}
            if "cmtype=page" in url:
                return {"query": {"categorymembers": [{"title": "Малая теорема Ферма"}]}}
            return {}

        class Http:
            get_json = staticmethod(fake_get_json)

        class Sources:
            http = Http()

        class Online:
            sources = Sources()

            def choose_next(self, domain=None):
                return None

            def build_site(self):
                return Path("dist")

        kernel = SciencePulseKernel(self.config, self.storage, Online())
        report = kernel.expand_deep(count=2)
        self.assertGreaterEqual(report["deep_added"], 1)
        deep_posts = [
            post for post in self.storage.list_posts(status="ready", limit=100)
            if (post.meta or {}).get("deep_origin")
        ]
        self.assertTrue(deep_posts)
        self.assertTrue(all("complexity_tier" in (post.meta or {}) for post in deep_posts))


if __name__ == "__main__":
    unittest.main()
