import unittest

from accessibility_auditor.router import classify_task_rules


class RouterRuleTests(unittest.TestCase):
    def test_alt_text_rule(self):
        result = classify_task_rules("The figure is missing alternative text.")
        self.assertEqual(result["task"], "alt_text")

    def test_table_rule(self):
        result = classify_task_rules("The table needs column headers and scope attributes.")
        self.assertEqual(result["task"], "table_summary")

    def test_heading_rule(self):
        result = classify_task_rules("The heading hierarchy skips from H1 to H3.")
        self.assertEqual(result["task"], "semantic_structure")

    def test_unsupported_rule(self):
        result = classify_task_rules("The embedded font has a CIDSet problem.")
        self.assertEqual(result["task"], "unsupported")


if __name__ == "__main__":
    unittest.main()
