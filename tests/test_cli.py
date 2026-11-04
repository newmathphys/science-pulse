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


if __name__ == "__main__":
    unittest.main()