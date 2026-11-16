import unittest

from tests import SNAPSHOTS
from uitestgen.snapshot import parse_hierarchy
from uitestgen.validator import ABSENT, AMBIGUOUS, FOUND, IndexedValidator
from uitestgen.workload import make_selectors, scale_xml


class WorkloadTest(unittest.TestCase):
    def setUp(self):
        self.xml_text = (SNAPSHOTS / "settings_main.xml").read_text(encoding="utf-8")
        self.nodes = parse_hierarchy(self.xml_text)

    def test_selector_mix_is_deterministic_and_proportional(self):
        first = make_selectors(self.nodes, 50, seed=3)
        self.assertEqual(first, make_selectors(self.nodes, 50, seed=3))
        kinds = [kind for kind, _ in first]
        self.assertEqual({k: kinds.count(k) for k in set(kinds)},
                         {"unique": 20, "compound": 10, "ambiguous": 10, "absent": 10})

    def test_scaling_multiplies_nodes_and_keeps_outcomes(self):
        scaled = parse_hierarchy(scale_xml(self.xml_text, 4))
        self.assertEqual(len(scaled), 4 * len(self.nodes))
        small, large = IndexedValidator(self.nodes), IndexedValidator(scaled)
        expected = {"unique": {FOUND}, "absent": {ABSENT}, "ambiguous": {AMBIGUOUS}}
        for kind, selector in make_selectors(self.nodes, 50, seed=3):
            before, after = small.validate(selector), large.validate(selector)
            if kind in expected:
                self.assertIn(before.status, expected[kind])
            if before.status != AMBIGUOUS:
                self.assertEqual(before, after)
            else:
                self.assertEqual(after.status, AMBIGUOUS)

    def test_scale_factor_must_be_positive(self):
        with self.assertRaises(ValueError):
            scale_xml(self.xml_text, 0)


if __name__ == "__main__":
    unittest.main()
