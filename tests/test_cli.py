import unittest

from science_pulse.cli import build_parser


class CliParserTests(unittest.TestCase):
    def test_all_commands_registered(self):
        parser = build_parser()
        # Парсер должен знать все команды (включая новые: limits/verify/foundation/voice).
        expected = {
            "init", "status", "harvest", "publish", "run", "site", "book", "voice",
            "standards", "quarantine", "reject", "preflight", "verify", "foundation",
            "limits", "admin", "daemon", "sources", "add", "checkpoint", "metrics",
            "invariants", "edge", "formal", "state", "retranslate", "drop", "recard", "reset",
            "post", "clean-start", "staged",
        }
        actions = [
            action for action in parser._actions
            if getattr(action, "choices", None)
        ]
        subparsers = next(a for a in parser._actions if hasattr(a, "choices") and isinstance(a.choices, dict))
        self.assertTrue(expected.issubset(set(subparsers.choices)), expected - set(subparsers.choices))

    def test_limits_set_parses_three_args(self):
        parser = build_parser()
        args = parser.parse_args(["limits", "--set", "threads", "max_caption_chars", "600"])
        self.assertEqual(args.set, ["threads", "max_caption_chars", "600"])
        self.assertEqual(args.func.__name__, "cmd_limits")

    def test_publish_video_flag(self):
        parser = build_parser()
        args = parser.parse_args(["publish", "--video"])
        self.assertTrue(args.video)
        args = parser.parse_args(["publish", "--no-video"])
        self.assertTrue(args.no_video)

    def test_standards_set_parses(self):
        parser = build_parser()
        args = parser.parse_args(["standards", "--set", "min_letters", "240"])
        self.assertEqual(args.set, ["min_letters", "240"])


class RecardDryRunTests(unittest.TestCase):
    """`recard --dry-run` рендерит карточки без токенов Telegram (картинки для сайта/CI)."""

    def test_recard_dry_run_without_tokens(self):
        import argparse
        import tempfile
        from pathlib import Path

        from science_pulse.cli import cmd_recard
        from science_pulse.config import Config
        from science_pulse.models import PublishResult
        from science_pulse.sources.offline import OfflineBunkerSource
        from science_pulse.storage import Storage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(raw={}, root=root)
            config.ensure_dirs()
            storage = Storage(config.db_path)
            post = OfflineBunkerSource(config).synthesize(0)
            storage.add_post(post)
            storage.record_publication(
                post.id,
                PublishResult(platform="telegram", ok=True, external_id="1", url="https://t.me/x/1"),
            )
            storage.mark_published(post.id)
            self.assertFalse(config.telegram_token)  # токенов нет — dry-run обязан работать

            args = argparse.Namespace(
                config=None, root=str(root), limit=10, post_id=None, dry_run=True, engine="pillow"
            )
            code = cmd_recard(args)
            self.assertEqual(code, 0)
            self.assertTrue((Path(config.cards_dir) / f"{post.id}.png").is_file())


class CleanStartTests(unittest.TestCase):
    """`clean-start`: сброс состояния + VACUUM + пересборка сайта (с --yes)."""

    def test_requires_yes(self):
        import argparse

        from science_pulse.cli import cmd_clean_start

        args = argparse.Namespace(config=None, root=None, yes=False)
        self.assertEqual(cmd_clean_start(args), 2)

    def test_resets_and_rebuilds(self):
        import argparse
        import tempfile
        from pathlib import Path

        from science_pulse.cli import cmd_clean_start
        from science_pulse.config import Config
        from science_pulse.sources.offline import OfflineBunkerSource
        from science_pulse.storage import Storage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(raw={}, root=root)
            config.ensure_dirs()
            storage = Storage(config.db_path)
            storage.add_post(OfflineBunkerSource(config).synthesize(0))
            self.assertGreater(storage.count(), 0)

            args = argparse.Namespace(config=None, root=str(root), yes=True)
            self.assertEqual(cmd_clean_start(args), 0)
            self.assertEqual(Storage(config.db_path).count(), 0)
            self.assertTrue((root / "dist" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()