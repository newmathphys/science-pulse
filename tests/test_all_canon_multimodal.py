import re
import unittest

from science_pulse.config import Config
from science_pulse.site import SiteBuilder
from science_pulse.sources.history_canon import CANON, HistoryCanonSource
from science_pulse.text import clean_latex_for_telegram, check_unmapped_latex, latex_to_unicode
from science_pulse.voice import math_to_spoken_russian


class CanonMultimodalTests(unittest.TestCase):
    def setUp(self):
        self.source = HistoryCanonSource(Config(raw={}))

    def test_all_60_formulas_are_clean(self):
        for index, node in enumerate(CANON):
            formula = node.get("formula_latex") or node.get("formula_plain") or ""
            self.assertEqual(check_unmapped_latex(formula), [], node["id"])
            unicode_value = latex_to_unicode(formula)
            self.assertNotIn("\\", unicode_value, node["id"])
            self.assertNotIn("land", unicode_value.lower(), node["id"])
            self.assertNotIn("lor", unicode_value.lower(), node["id"])
            self.assertNotRegex(unicode_value, r"\bA\s+B\b|\bB\s+A\b", node["id"])
            spoken = math_to_spoken_russian(formula)
            self.assertNotIn("\\", spoken, node["id"])

    def test_site_legend_has_no_latex_fragments(self):
        for index, node in enumerate(CANON):
            post = self.source._build(node, index)
            legend = SiteBuilder._formula_legend(post)
            self.assertNotIn("land", legend.lower(), node["id"])
            self.assertNotIn("lor", legend.lower(), node["id"])
            self.assertNotIn("\\", legend, node["id"])


if __name__ == "__main__":
    unittest.main()
