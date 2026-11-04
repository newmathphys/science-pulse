import unittest
from pathlib import Path

from science_pulse.formal import check_lean, lean_available

ROOT = Path(__file__).resolve().parents[1]


class FormalTests(unittest.TestCase):
    @unittest.skipUnless(lean_available(), "lean не установлен")
    def test_lean_proofs_compile(self):
        result = check_lean(ROOT)
        self.assertTrue(result.ok, msg=result.stderr or result.stdout or result.error)

    def test_missing_file_reported(self):
        result = check_lean(ROOT / "does-not-exist")
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
