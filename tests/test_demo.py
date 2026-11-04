import tempfile
import unittest
from pathlib import Path

from science_pulse.config import Config
from science_pulse.demo import TOUR_ARCHETYPES, _archetype_posts, format_variants, network_variants
from science_pulse.platforms_info import PlatformRules


class DemoTourTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(raw={})

    def test_archetype_posts_cover_all_visual_types(self):
        posts = _archetype_posts(self.config)
        self.assertEqual(len(posts), len(TOUR_ARCHETYPES))
        from science_pulse.cards_academic import pick_visual_type

        picked = {pick_visual_type(post) for post in posts}
        self.assertEqual(picked, {"standard_plot", "code_booktabs", "diptych_insar",
                                  "cheatsheet_table", "timeline_evolution"})

    def test_variants_respect_platform_limits(self):
        post = _archetype_posts(self.config)[0]
        variants = network_variants(post, self.config, "https://example.org")
        rules = PlatformRules()
        self.assertLessEqual(len(variants["telegram"]), rules.limit("telegram"))
        self.assertLessEqual(len(variants["bluesky"]), rules.limit("bluesky"))
        self.assertLessEqual(len(variants["mastodon"]), rules.limit("mastodon"))
        self.assertLessEqual(len(variants["vk"]), rules.limit("vk"))
        for name in ("telegram", "threads", "bluesky", "discord", "mastodon", "vk"):
            self.assertTrue(variants[name].strip(), name)

    def test_format_variants_is_message_list(self):
        post = _archetype_posts(self.config)[0]
        messages = format_variants(post, network_variants(post, self.config, "https://x.org"))
        self.assertEqual(len(messages), 7)  # заголовок + 6 площадок
        for message in messages:
            self.assertLess(len(message), 3900, "сообщение не должно разрезаться Telegram")
            self.assertEqual(message.count("<blockquote>"), message.count("</blockquote>"))

    def test_full_description_structure(self):
        from science_pulse.publishers.base import build_full_description

        post = _archetype_posts(self.config)[2]  # InSAR: есть эпоха/константы/применение/тема
        text = build_full_description(post, 4096, "https://x.org")
        for marker in ("Разбор", "Формула", "Где работает сегодня", "Константы", "Тема", "https://x.org"):
            self.assertIn(marker, text, marker)
        self.assertLessEqual(len(text), 4096)
        # полный разбор не обрезается до абзаца: тело поста входит целиком
        self.assertIn(post.body[:80], text)

    def test_full_description_longer_than_caption(self):
        from science_pulse.publishers.base import build_full_description, build_rich_telegram_caption

        post = _archetype_posts(self.config)[0]
        self.assertGreater(len(build_full_description(post, 4096, "")),
                           len(build_rich_telegram_caption(post, 1024, "")))

    def test_variants_change_with_limits(self):
        post = _archetype_posts(self.config)[0]
        short = Config(raw={"platform_rules": {"threads": {"max_caption_chars": 200}}})
        long = Config(raw={"platform_rules": {"threads": {"max_caption_chars": 900}}})
        self.assertLess(len(network_variants(post, short, "")["threads"]),
                        len(network_variants(post, long, "")["threads"]) + 1)


if __name__ == "__main__":
    unittest.main()