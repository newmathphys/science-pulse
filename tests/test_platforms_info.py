import unittest

from science_pulse.platforms_info import (
    LANGUAGES,
    PLATFORMS,
    format_about,
    format_platform,
    format_platforms,
    normalize_lang,
    platform_names,
)


class PlatformsInfoTests(unittest.TestCase):
    def test_catalog_is_bilingual(self):
        self.assertGreaterEqual(len(PLATFORMS), 6)
        for name, data in PLATFORMS.items():
            self.assertTrue(data.get("emoji"), name)
            self.assertTrue(data.get("env"), name)
            for lang in LANGUAGES:
                self.assertIn(lang, data, f"{name}/{lang}")
                for field in ("title", "what", "limits", "image", "metrics", "notes"):
                    self.assertTrue(data[lang].get(field), f"{name}/{lang}/{field}")

    def test_normalize_lang(self):
        self.assertEqual(normalize_lang("EN"), "en")
        self.assertEqual(normalize_lang("xx"), "ru")
        self.assertEqual(normalize_lang(None), "ru")

    def test_format_platform_both_languages(self):
        ru = format_platform("telegram", "ru")
        en = format_platform("telegram", "en")
        self.assertIn("Что умеет", ru)
        self.assertIn("Capabilities", en)
        self.assertIn("TG_BOT_TOKEN", ru)
        self.assertIn("TG_BOT_TOKEN", en)

    def test_format_platform_unknown(self):
        self.assertIn("не найдена", format_platform("nope", "ru"))
        self.assertIn("Unknown", format_platform("nope", "en"))

    def test_format_platforms_lists_all(self):
        text = format_platforms("en", {"telegram": True, "threads": False})
        for data in PLATFORMS.values():
            self.assertIn(data["en"]["title"], text)
        self.assertIn("no tokens", text)

    def test_platform_names(self):
        self.assertEqual(set(platform_names()), set(PLATFORMS.keys()))

    def test_format_about(self):
        ru = format_about("ru", "https://example.org/pult.html")
        en = format_about("en")
        self.assertIn("Как работает пульт", ru)
        self.assertIn("https://example.org/pult.html", ru)
        self.assertIn("data/science.db", ru)
        self.assertIn("How the pult works", en)
        self.assertIn("data/science.db", en)


if __name__ == "__main__":
    unittest.main()
