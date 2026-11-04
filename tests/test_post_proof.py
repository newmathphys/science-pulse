import unittest

from science_pulse.models import Post
from science_pulse.post_proof import build_post_proof, format_proof_line, merkle_hash


def make_post(**fields):
    values = dict(
        id="proof1",
        domain="physics",
        title="Тест вычислительного паспорта",
        hook="Зачем считать точно?",
        body="Проверка CODATA-расчёта и песочницы кода в вычислительном паспорте поста.",
        formula_plain="x**2 + 1",
        source_name="test",
    )
    values.update(fields)
    return Post(**values)


class PostProofTests(unittest.TestCase):
    def test_computed_example_has_formula_values(self):
        proof = build_post_proof(make_post())
        self.assertIn("x(0) = 1", proof["computed_example"])
        self.assertIn("x(1) = 2", proof["computed_example"])
        self.assertIn("x(2) = 5", proof["computed_example"])

    def test_codata_values(self):
        post = make_post(formula_plain="x", meta={"constants_used": ["c", "hbar"]})
        proof = build_post_proof(post)
        self.assertIn("CODATA", proof["computed_example"])
        self.assertIn("299792458", proof["computed_example"])

    def test_dangerous_import_blocked(self):
        proof = build_post_proof(make_post(code="import os\nos.system('echo hi')"))
        self.assertFalse(proof["code_proof"]["ok"])
        self.assertIn("запрещённый импорт", proof["code_proof"]["summary"])

    def test_eval_blocked(self):
        proof = build_post_proof(make_post(code="print(eval('1+1'))"))
        self.assertFalse(proof["code_proof"]["ok"])
        self.assertIn("eval", proof["code_proof"]["summary"])

    def test_safe_code_runs(self):
        proof = build_post_proof(make_post(code="print(sum(range(5)))"))
        self.assertTrue(proof["code_proof"]["ok"], proof["code_proof"]["summary"])
        self.assertIn("AST & Run OK", proof["code_proof"]["summary"])

    def test_merkle_deterministic_and_chained(self):
        post = make_post()
        first = build_post_proof(post)["merkle_hash"]
        second = build_post_proof(make_post())["merkle_hash"]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(merkle_hash(post, prev_merkle=first), first)

    def test_proof_written_to_meta(self):
        post = make_post()
        build_post_proof(post)
        self.assertIn("proof", post.meta)
        self.assertIn("merkle_hash", post.meta["proof"])
        self.assertTrue(format_proof_line(post.meta["proof"]).startswith("🔢"))


if __name__ == "__main__":
    unittest.main()
