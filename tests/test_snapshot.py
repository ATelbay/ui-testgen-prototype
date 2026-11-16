import unittest

from tests import FIXTURES
from uitestgen.snapshot import SnapshotError, load_snapshot, parse_bounds, parse_hierarchy


class ParseBoundsTest(unittest.TestCase):
    def test_parses_uiautomator_bounds(self):
        self.assertEqual(parse_bounds("[48,120][1032,220]"), (48, 120, 1032, 220))

    def test_rejects_malformed_bounds(self):
        with self.assertRaises(SnapshotError):
            parse_bounds("48,120,1032,220")


class ParseHierarchyTest(unittest.TestCase):
    def setUp(self):
        self.nodes = load_snapshot(FIXTURES / "login.xml")

    def test_flattens_in_preorder_with_parents_and_depth(self):
        self.assertEqual(len(self.nodes), 6)
        root, title = self.nodes[0], self.nodes[1]
        self.assertEqual((root.parent, root.depth), (None, 0))
        self.assertEqual((title.parent, title.depth), (0, 1))
        self.assertEqual(title.resource_id, "org.example.demo:id/title")
        self.assertEqual([n.index for n in self.nodes], list(range(6)))

    def test_reads_flags_and_visibility(self):
        submit, help_link = self.nodes[4], self.nodes[5]
        self.assertTrue(submit.clickable)
        self.assertFalse(submit.enabled)
        self.assertFalse(help_link.visible)  # zero-width bounds

    def test_rejects_malformed_xml_and_wrong_root(self):
        with self.assertRaises(SnapshotError):
            parse_hierarchy("<hierarchy><node></hierarchy>")
        with self.assertRaises(SnapshotError):
            parse_hierarchy("<screen />")


if __name__ == "__main__":
    unittest.main()
