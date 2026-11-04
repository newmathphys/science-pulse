import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from science_pulse.config import Config
from science_pulse.models import Post
from science_pulse.radio import (
    AMBIENT_CHORD_HZ,
    RADIO_JS,
    build_podcast_xml,
    build_radio_mix,
    current_slot,
    episode_entry,
    mix_plan,
    radio_page_html,
    radio_playlist,
    radio_status,
    rtmp_argv,
    slot_entry,
    write_chapters,
    write_radio,
)


def make_post(post_id="p1", section="1.1", status="published", domain="math", **meta):
    payload = {"section_num": section, "scientist": "Пифагор", "era": "530 г. до н.э."}
    payload.update(meta)
    return Post(
        id=post_id,
        domain=domain,
        title=f"Теорема {post_id}",
        hook="Почему это работает?",
        body="Краткая суть открытия.",
        formula_plain="a² + b² = c²",
        status=status,
        published_at="2026-01-02T09:00:00+00:00" if status == "published" else "",
        source_name="Фундамент Науки",
        meta=payload,
    )


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_sections_are_ordered_and_prepared_appended(self):
        posts = [
            make_post("p3", "1.3"),
            make_post("p1", "1.1"),
            make_post("p2", "1.2"),
            make_post("ready1", "2.1", status="ready", foundation_id="newton_gravity"),
        ]
        playlist = radio_playlist(posts, self.config)
        self.assertEqual([item["section"] for item in playlist], ["1.1", "1.2", "1.3", "2.1"])
        self.assertEqual(playlist[-1]["status"], "ready")
        self.assertEqual(playlist[0]["label"], "§ 1.1 • Теорема p1")

    def test_non_canon_ready_posts_are_skipped(self):
        posts = [make_post("p1", "1.1"), make_post("free", "", status="ready")]
        playlist = radio_playlist(posts, self.config)
        self.assertEqual([item["id"] for item in playlist], ["p1"])

    def test_audio_flag_follows_file_presence(self):
        audio_dir = self.config.data_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "p1.mp3").write_bytes(b"ID3")
        playlist = radio_playlist([make_post("p1", "1.1"), make_post("p2", "1.2")], self.config)
        self.assertTrue(playlist[0]["audio"])
        self.assertFalse(playlist[1]["audio"])

    def test_entry_notes_come_from_formula(self):
        entry = episode_entry(make_post("p1", "1.1"), "", self.config.data_dir / "audio")
        self.assertTrue(entry["notes"])
        self.assertTrue(all(note > 0 for note in entry["notes"]))

    def test_slot_entry_is_cyclic(self):
        posts = [make_post("p1", "1.1"), make_post("p2", "1.2")]
        playlist = radio_playlist(posts, self.config)
        picked = slot_entry(playlist)
        self.assertIn(picked["id"], {"p1", "p2"})
        self.assertEqual(current_slot(), current_slot())
        self.assertGreaterEqual(current_slot(), 0)


class PodcastTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(
            raw={"data_dir": "data", "dist_dir": "dist", "site_base_url": "https://example.org/pulse"},
            root=Path(self.tmp.name),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_podcast_is_valid_rss_with_enclosures(self):
        entries = [
            {"id": "p1", "label": "§ 1.1 • Теорема", "url": "https://example.org/post/p1.html",
             "hook": "Крючок", "scientist": "Пифагор", "audio": "audio/p1.mp3"},
            {"id": "p2", "label": "§ 1.2", "url": "https://example.org/post/p2.html",
             "hook": "", "scientist": "", "audio": ""},
        ]
        xml = build_podcast_xml(entries, self.config)
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "rss")
        items = root.findall("./channel/item")
        self.assertEqual(len(items), 1)
        enclosure = items[0].find("enclosure")
        self.assertEqual(enclosure.get("type"), "audio/mpeg")
        self.assertTrue(enclosure.get("url").endswith("audio/p1.mp3"))
        self.assertEqual(root.find("./channel/link").text, "https://example.org/pulse/radio.html")


class RadioPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_page_has_webaudio_mediasession_and_playlist(self):
        entries = radio_playlist([make_post("p1", "1.1")], self.config)
        page = radio_page_html(entries, self.config)
        for marker in ("SP_RADIO", "AudioContext", "mediaSession", "AnalyserNode",
                       "getByteTimeDomainData", "speechSynthesis", "radio-list", "podcast.xml"):
            self.assertIn(marker, page)
        self.assertIn("§ 1.1", page)

    def test_js_declares_pythagorean_ambient(self):
        self.assertIn("220", RADIO_JS)
        self.assertIn("330", RADIO_JS)
        self.assertIn("440", RADIO_JS)
        self.assertEqual(list(AMBIENT_CHORD_HZ), [220.0, 330.0, 440.0])

    def test_write_radio_creates_three_artifacts(self):
        dist = self.config.dist_dir
        dist.mkdir(parents=True, exist_ok=True)
        result = write_radio(dist, [make_post("p1", "1.1")], self.config)
        self.assertTrue(Path(result["radio"]).is_file())
        self.assertTrue(Path(result["podcast"]).is_file())
        self.assertTrue(Path(result["playlist"]).is_file())
        self.assertEqual(result["episodes"], 1)


class MixAndRtmpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = Config(raw={"data_dir": "data", "dist_dir": "dist"}, root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mix_plan_collects_audiograms(self):
        audiogram = self.config.data_dir / "audiogram"
        audiogram.mkdir(parents=True, exist_ok=True)
        (audiogram / "p1.mp4").write_bytes(b"not-a-video")
        plan = mix_plan([make_post("p1", "1.1"), make_post("p2", "1.2")], self.config.data_dir)
        self.assertEqual([item["id"] for item in plan["chapters"]], ["p1"])
        self.assertGreater(plan["total_seconds"], 0)

    def test_chapters_file_format(self):
        plan = {"chapters": [{"start": 0, "label": "§ 1.1 Пифагор"},
                             {"start": 75, "label": "§ 1.2 Евклид"}], "total_seconds": 80}
        path = write_chapters(plan, self.root / "chapters.txt")
        text = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(text[0], "00:00 § 1.1 Пифагор")
        self.assertEqual(text[1], "01:15 § 1.2 Евклид")

    def test_mix_without_audiograms_returns_none(self):
        self.assertIsNone(
            build_radio_mix([make_post("p1", "1.1")], self.config.data_dir, self.root / "mix.mp4")
        )

    def test_rtmp_argv_streams_forever(self):
        argv = rtmp_argv("rtmps://dc4.rtmp.t.me/s/KEY", self.root / "mix.mp4")
        self.assertEqual(argv[0], "ffmpeg")
        self.assertIn("-stream_loop", argv)
        self.assertIn("-1", argv)
        self.assertEqual(argv[-1], "rtmps://dc4.rtmp.t.me/s/KEY")
        self.assertIn("flv", argv)

    def test_radio_status_summary(self):
        status = radio_status([make_post("p1", "1.1")], self.config)
        self.assertEqual(status["episodes"], 1)
        self.assertEqual(status["slot_seconds"], 21600)
        self.assertIn("§ 1.1", status["now"])


if __name__ == "__main__":
    unittest.main()
