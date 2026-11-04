import unittest

from science_pulse.config import Config
from science_pulse.sources.github_raw import GitHubRawSource
from science_pulse.sources.oeis import OEISSource
from science_pulse.sources.rosetta import RosettaSource
from science_pulse.sources.stackexchange import StackExchangeSource
from science_pulse.sources.wikipedia import WikipediaSource


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(raw={})

    def test_stackexchange_build_post(self):
        source = StackExchangeSource(self.config)
        questions = {
            10: {
                "question_id": 1,
                "title": "Why does the harmonic series diverge?",
                "score": 42,
                "view_count": 1000,
                "accepted_answer_id": 10,
            }
        }
        answers = [
            {
                "answer_id": 10,
                "score": 30,
                "body": "<p>The series diverges because the terms do not approach zero fast enough, and the partial sums grow without bound: $\\sum_{n=1}^{\\infty} \\frac{1}{n} = \\infty$. This is a classical result.</p>",
            }
        ]
        posts = source.build_posts(questions, answers, "math", "math")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].domain, "math")
        self.assertIn("\\sum", posts[0].formula_latex)
        self.assertTrue(posts[0].source_url.endswith("/a/10"))

    def test_stackexchange_extract_formulas(self):
        formulas = StackExchangeSource.extract_formulas(
            "Text $E=mc^2$ and $$\\int_0^1 x^2 dx = 1/3$$ and $x$."
        )
        self.assertTrue(any("E=mc^2" in formula for formula in formulas))
        self.assertTrue(any("\\int" in formula for formula in formulas))

    def test_oeis_pickers(self):
        self.assertIn("a(n)", OEISSource._pick_formula(["a(n) = a(n-1)+a(n-2)", "other"], "1,1,2"))
        code = OEISSource._pick_python(["(Python) def f(n):\n    return n", "(PARI) x"])
        self.assertIn("def f", code)

    def test_oeis_sequence_not_cut_mid_number(self):
        """Хвост data, обрезанный посередине числа, не должен попадать в пост."""
        source = OEISSource(self.config)
        payload = "1," * 299 + "9876543210,2,3"  # обрезка на 600 символов ломает число
        source.http = type("Stub", (), {"get_json": lambda *a, **k: [{
            "number": 45, "name": "Test sequence", "data": payload,
            "formula": ["a(n) = a(n-1) + a(n-2)"], "program": [],
        }]})()
        post = source.fetch_sequence("A000045")
        tokens = {part.strip() for part in payload.split(",")}
        self.assertTrue(post.meta["sequence"])
        for value in post.meta["sequence"]:
            self.assertIn(value, tokens)  # ни одного обрезанного числа

    def test_rosetta_wikitext(self):
        wikitext = "Intro about sorting.\n\n=={{header|Python}}==\n<syntaxhighlight lang=\"python\">\ndef qsort(a):\n    return sorted(a)\n</syntaxhighlight>\n"
        intro = RosettaSource._clean_wikitext(wikitext.split("=={{header|", 1)[0])
        self.assertIn("Intro", intro)
        code = RosettaSource._extract_python(wikitext)
        self.assertIn("def qsort", code)

    def test_github_markdown(self):
        parsed = GitHubRawSource._parse_markdown(
            "# Fast Fourier Transform\n\nAn algorithm. Formula $X_k=\\sum x_n e^{-i2\\pi kn/N}$.\n\n```python\nprint(1)\n```"
        )
        self.assertEqual(parsed["title"], "Fast Fourier Transform")
        self.assertIn("algorithm", parsed["body"])
        self.assertIn("print(1)", parsed["code"])
        self.assertIn("\\sum", parsed["formula"])

    def test_github_json(self):
        parsed = GitHubRawSource._parse_json('{"title":"Fact","text":"Body text","formula":"E=mc^2"}')
        self.assertEqual(parsed["title"], "Fact")
        self.assertEqual(parsed["formula"], "E=mc^2")

    def test_wikipedia_math(self):
        formulas = WikipediaSource._extract_math("Text $a^2+b^2=c^2$ and $$\\pi$$")
        self.assertTrue(formulas)


if __name__ == "__main__":
    unittest.main()
