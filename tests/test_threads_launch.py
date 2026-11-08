import os
import unittest
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.models import CardArtifact, Post
from science_pulse.publishers.base import PublishContext
from science_pulse.publishers.threads import ThreadsPublisher


def make_post():
    return Post(
        id="th1",
        domain="math",
        title="Теорема Пифагора",
        hook="Почему формула работает?",
        body="Теорема связывает катеты и гипотенузу прямоугольного треугольника. " * 3,
        formula_latex="a^2 + b^2 = c^2",
        formula_plain="a² + b² = c²",
        source_name="test",
    )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class ThreadsLaunchTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(raw={"threads": {"user_id": "123"}})
        self.card = CardArtifact(path="/tmp/card.png", data=b"png", width=1080, height=1080)
        self.env = patch.dict(os.environ, {"TH_ACCESS_TOKEN": "token"}, clear=False)
        self.env.start()
        self.publisher = ThreadsPublisher(self.config)

    def tearDown(self):
        self.env.stop()

    def test_only_keys_text_post(self):
        calls = []

        def fake_post(url, data=None, timeout=None):
            calls.append(dict(data or {}))
            if url.endswith("/threads"):
                return FakeResponse({"id": "container-1"})
            return FakeResponse({"id": "post-1"})

        with patch("science_pulse.publishers.threads.requests.post", side_effect=fake_post), \
                patch("science_pulse.publishers.threads.time.sleep", return_value=None):
            result = self.publisher.publish(make_post(), self.card, PublishContext())

        self.assertTrue(result.ok)
        self.assertEqual(result.external_id, "post-1")
        self.assertEqual(calls[0]["media_type"], "TEXT")
        self.assertNotIn("image_url", calls[0])
        self.assertEqual(len(calls), 2)

    def test_image_failure_falls_back_to_text(self):
        calls = []

        def fake_post(url, data=None, timeout=None):
            calls.append(dict(data or {}))
            if url.endswith("/threads"):
                if data.get("media_type") == "IMAGE":
                    return FakeResponse({"error": "image_url rejected"})
                return FakeResponse({"id": "container-text"})
            return FakeResponse({"id": "post-text"})

        with patch("science_pulse.publishers.threads.requests.post", side_effect=fake_post), \
                patch("science_pulse.publishers.threads.time.sleep", return_value=None):
            result = self.publisher.publish(
                make_post(), self.card, PublishContext(public_card_url="https://example.org/card.png")
            )

        self.assertTrue(result.ok)
        self.assertEqual(calls[0]["media_type"], "IMAGE")
        self.assertEqual(calls[1]["media_type"], "TEXT")
        self.assertEqual(result.external_id, "post-text")

    def test_unavailable_without_keys(self):
        with patch.dict(os.environ, {"TH_ACCESS_TOKEN": ""}, clear=False):
            publisher = ThreadsPublisher(self.config)
            self.assertFalse(publisher.available())


if __name__ == "__main__":
    unittest.main()
