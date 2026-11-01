"""Fail-closed regression for a negative semantic verdict with empty details.

Tests the exact worker.assess decision clause, without importing GPU, models,
service configuration or private image fixtures. Not an end-to-end image test.
"""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "worker" / "worker.py"


def semantic_clause():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SOURCE))
    assess = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "assess")
    candidates = [
        n for n in ast.walk(assess)
        if isinstance(n, ast.If)
        and ast.get_source_segment(source, n.test).replace(" ", "") == 'semantic=="failed"'
    ]
    if len(candidates) != 1:
        raise AssertionError("Cannot isolate expected worker.assess semantic status branch")
    return compile(ast.Module(body=[candidates[0]], type_ignores=[]), str(SOURCE), "exec")


class SemanticFailureContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = semantic_clause()

    def check_clause(self, semantic, details, prior=None):
        scope = {
            "semantic": semantic,
            "validation": {"reasons": details},
            "reasons": list(prior or []),
            "metrics": {},
        }
        exec(self.code, scope)
        return scope["reasons"]

    def test_failed_without_reasons_cannot_be_accepted(self):
        self.assertTrue(self.check_clause("failed", []))

    def test_failed_with_specific_reason_is_preserved(self):
        self.assertEqual(self.check_clause("failed", ["wrong wardrobe"]), ["wrong wardrobe"])

    def test_passed_with_no_reasons_does_not_create_failure(self):
        self.assertEqual(self.check_clause("passed", []), [])

    def test_existing_failure_is_not_suppressed(self):
        self.assertIn("wrong size", self.check_clause("failed", [], ["wrong size"]))


if __name__ == "__main__":
    unittest.main()
