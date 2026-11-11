import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from science_pulse.config import Config
from science_pulse.media_attach import attach_threads_video
from science_pulse.models import Post, PublishResult
from science_pulse.storage import Storage


def make_post():
    return Post(
        id="m1",
        domain="math",
        title="Теорема",
        hook="Почему?",
        body="Тело поста.",
        source_name="test",
    )


class MediaAttachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tmp.name) / "science.db")
        self.config = Config(raw={
            "site_base_url": "https://example.org/science-pulse",
            "data_dir": self.tmp.name,
            "threads": {"user_id": "123"},
        })
        post = make_post()
        self.storage.add_post(post)
        self.storage.mark_published(post.id)
        self.storage.record_publication(
            post.id,
            PublishResult(platform="threads", ok=True, external_id="parent-1"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_attaches_video_and_saves_meta(self):
        with patch("science_pulse.media_attach.audiogram_for_post", return_value=Path("/tmp/a.mp4")), \
                patch("science_pulse.media_attach._wait_public", return_value=True), \
                patch("science_pulse.media_attach.ThreadsPublisher") as publisher_cls:
            publisher_cls.return_value.publish_video_reply.return_value = PublishResult(
                platform="threads", ok=True, external_id="video-1", url="https://threads.net/t/video-1"
            )
            result = attach_threads_video(make_post(), self.config, self.storage)

        self.assertTrue(result.ok)
        self.assertEqual(result.external_id, "video-1")
        publisher_cls.return_value.publish_video_reply.assert_called_once()
        args = publisher_cls.return_value.publish_video_reply.call_args.args
        self.assertEqual(args[0], "parent-1")
        self.assertIn("/audiogram/m1.mp4", args[1])
        saved = self.storage.get_post("m1")
        self.assertEqual(saved.meta.get("threads_video_reply_id"), "video-1")

    def test_skips_when_already_attached(self):
        self.storage.set_post_meta("m1", "threads_video_reply_id", "video-old")
        result = attach_threads_video(self.storage.get_post("m1"), self.config, self.storage)
        self.assertTrue(result.ok)
        self.assertEqual(result.external_id, "video-old")
        self.assertTrue(result.meta.get("skipped"))


if __name__ == "__main__":
    unittest.main()
