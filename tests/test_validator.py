from itertools import combinations
import unittest

from tests import FIXTURES, SNAPSHOTS
from uitestgen.snapshot import load_snapshot
from uitestgen.validator import (ABSENT, AMBIGUOUS, FIELDS, FOUND, IndexedValidator,
                                 NaiveValidator, Selector)
from uitestgen.workload import make_selectors

IMPLEMENTATIONS = (NaiveValidator, IndexedValidator)


class ValidatorContractTest(unittest.TestCase):
    """The same contract is checked for every implementation."""

    def setUp(self):
        self.nodes = load_snapshot(FIXTURES / "login.xml")

    def check(self, selector, status, matches, valid):
        for cls in IMPLEMENTATIONS:
            with self.subTest(impl=cls.name, selector=selector):
                result = cls(self.nodes).validate(selector)
                self.assertEqual(result.status, status)
                self.assertEqual(result.matches, matches)
                self.assertEqual(result.is_valid, valid)

    def test_unique_resource_id_is_valid(self):
        self.check(Selector(resource_id="org.example.demo:id/email"), FOUND, (2,), True)

    def test_duplicate_text_is_ambiguous(self):
        self.check(Selector(text="Sign in"), AMBIGUOUS, (1, 4), False)

    def test_compound_selector_resolves_ambiguity(self):
        self.check(Selector(text="Sign in", class_name="android.widget.TextView"),
                   FOUND, (1,), True)

    def test_missing_element_is_absent(self):
        self.check(Selector(resource_id="org.example.demo:id/missing"), ABSENT, (), False)

    def test_unique_but_disabled_or_invisible_is_not_valid(self):
        self.check(Selector(resource_id="org.example.demo:id/submit"), FOUND, (4,), False)
        self.check(Selector(text="Help"), FOUND, (5,), False)

    def test_selector_requires_a_criterion(self):
        with self.assertRaises(ValueError):
            Selector()


def attribute_combinations(node):
    """Every non-empty conjunction of the node's non-empty attributes."""
    values = [(field, getattr(node, field)) for field, _ in FIELDS if getattr(node, field)]
    for size in range(1, len(values) + 1):
        for subset in combinations(values, size):
            yield Selector(**dict(subset))


class ImplementationRegressionTest(unittest.TestCase):
    """Indexed lookup must not change any outcome on the captured screens."""

    def setUp(self):
        self.paths = sorted(SNAPSHOTS.glob("*.xml"))
        self.assertGreater(len(self.paths), 0, "no snapshots in data/snapshots")

    def assert_same(self, nodes, selectors, label):
        naive, indexed = NaiveValidator(nodes), IndexedValidator(nodes)
        for selector in selectors:
            expected, actual = naive.validate(selector), indexed.validate(selector)
            if expected != actual:
                self.fail("{}: {} -> naive {}, indexed {}".format(
                    label, selector, expected, actual))

    def test_naive_and_indexed_agree_on_benchmark_selectors(self):
        for path in self.paths:
            nodes = load_snapshot(path)
            selectors = [s for _, s in make_selectors(nodes, 100, seed=7)]
            self.assert_same(nodes, selectors, path.name)

    def test_naive_and_indexed_agree_on_all_attribute_combinations(self):
        # Covers conjunctions such as a shared resource-id plus a text value.
        checked = 0
        for path in self.paths:
            nodes = load_snapshot(path)
            selectors = [s for node in nodes for s in attribute_combinations(node)]
            checked += len(selectors)
            self.assert_same(nodes, selectors, path.name)
        self.assertGreater(checked, 1000)


if __name__ == "__main__":
    unittest.main()
