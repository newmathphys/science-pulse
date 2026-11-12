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
                patch.object(ThreadsPublisher, "_wait_container", return_value=(True, "")), \
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
                patch.object(ThreadsPublisher, "_wait_container", return_value=(True, "")), \
                patch("science_pulse.publishers.threads.time.sleep", return_value=None):
            result = self.publisher.publish(
                make_post(), self.card, PublishContext(public_card_url="https://example.org/card.png")
            )

        self.assertTrue(result.ok)
        self.assertEqual(calls[0]["media_type"], "IMAGE")
        self.assertEqual(calls[1]["media_type"], "TEXT")
        self.assertEqual(result.external_id, "post-text")

    def test_growth_chain_when_enabled(self):
        config = Config(raw={"threads": {"user_id": "123"}, "growth": {"threads": {"enabled": True}}})
        publisher = ThreadsPublisher(config)
        calls = []

        def fake_post(url, data=None, timeout=None):
            calls.append(dict(data or {}))
            if url.endswith("/threads"):
                return FakeResponse({"id": f"c{len(calls)}"})
            return FakeResponse({"id": f"p{len(calls)}"})

        with patch("science_pulse.publishers.threads.requests.post", side_effect=fake_post), \
                patch.object(ThreadsPublisher, "_wait_container", return_value=(True, "")), \
                patch("science_pulse.publishers.threads.time.sleep", return_value=None):
            result = publisher.publish(make_post(), self.card, PublishContext(site_url="https://example.org/post/th1"))

        self.assertTrue(result.ok)
        texts = [call.get("text", "") for call in calls if call.get("text")]
        self.assertGreaterEqual(len(texts), 2)
        self.assertNotIn("https://", texts[0])
        self.assertIn("example.org", texts[1])

    def test_video_first_publishes_video_before_card(self):
        config = Config(raw={"threads": {"user_id": "123", "video_first": True}})
        publisher = ThreadsPublisher(config)
        calls = []

        def fake_post(url, data=None, timeout=None):
            calls.append(dict(data or {}))
            if url.endswith("/threads"):
                return FakeResponse({"id": f"c{len(calls)}"})
            return FakeResponse({"id": f"p{len(calls)}"})

        with patch("science_pulse.publishers.threads.requests.post", side_effect=fake_post), \
                patch.object(ThreadsPublisher, "_wait_container", return_value=(True, "")), \
                patch("science_pulse.publishers.threads.time.sleep", return_value=None):
            result = publisher.publish(
                make_post(),
                self.card,
                PublishContext(
                    public_card_url="https://example.org/card.png",
                    video_url="https://example.org/video.mp4",
                ),
            )

        self.assertTrue(result.ok)
        containers = [call for call in calls if call.get("media_type")]
        self.assertEqual(containers[0]["media_type"], "VIDEO")
        self.assertEqual(containers[0]["video_url"], "https://example.org/video.mp4")
        self.assertEqual(containers[1]["media_type"], "IMAGE")
        self.assertTrue(result.meta["video_first"])

    def test_video_reply_uses_video_container(self):
        calls = []

        def fake_post(url, data=None, timeout=None):
            calls.append(dict(data or {}))
            if url.endswith("/threads"):
                return FakeResponse({"id": "video-container"})
            return FakeResponse({"id": "video-post"})

        with patch("science_pulse.publishers.threads.requests.post", side_effect=fake_post), \
                patch.object(ThreadsPublisher, "_wait_container", return_value=(True, "")), \
                patch("science_pulse.publishers.threads.time.sleep", return_value=None):
            result = self.publisher.publish_video_reply(
                "parent-1", "https://example.org/audiogram/th1.mp4", "Видеоразбор"
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.external_id, "video-post")
        self.assertEqual(calls[0]["media_type"], "VIDEO")
        self.assertEqual(calls[0]["video_url"], "https://example.org/audiogram/th1.mp4")
        self.assertEqual(calls[0]["reply_to_id"], "parent-1")

    def test_wait_container_finished(self):
        with patch("science_pulse.publishers.threads.requests.get",
                   return_value=FakeResponse({"status": "FINISHED"})):
            ok, error = self.publisher._wait_container("c1")
        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_wait_container_error(self):
        with patch("science_pulse.publishers.threads.requests.get",
                   return_value=FakeResponse({"status": "ERROR", "error_message": "bad image"})):
            ok, error = self.publisher._wait_container("c1")
        self.assertFalse(ok)
        self.assertIn("bad image", error)

    def test_image_mode(self):
        with patch.dict(os.environ, {"CF_WORKER_URL": ""}, clear=False):
            self.assertIn(ThreadsPublisher(self.config).image_mode(), {"text", "site"})
        with patch.dict(os.environ, {"CF_WORKER_URL": "https://worker.example"}, clear=False):
            self.assertEqual(ThreadsPublisher(self.config).image_mode(), "cloudflare")

    def test_unavailable_without_keys(self):
        with patch.dict(os.environ, {"TH_ACCESS_TOKEN": ""}, clear=False):
            publisher = ThreadsPublisher(self.config)
            self.assertFalse(publisher.available())


if __name__ == "__main__":
    unittest.main()
