"""Deterministic workloads for locator-validation benchmarks.

* ``scale_xml`` enlarges a real UI dump by appending renamed copies of its
  top-level subtrees, so the hierarchy grows while selectors generated for
  the original copy keep their outcome (unique stays unique, absent stays
  absent; class-only selectors stay ambiguous).
* ``make_selectors`` draws a fixed mix of selector kinds with a seed.
"""
import copy
import random
from typing import List, Sequence, Tuple
import xml.etree.ElementTree as ET

from .snapshot import UiNode
from .validator import Selector

RENAMED_ATTRIBUTES = ("resource-id", "text", "content-desc")

# Share of each selector kind in the generated mix.
SELECTOR_MIX = (
    ("unique", 0.4),
    ("compound", 0.2),
    ("ambiguous", 0.2),
    ("absent", 0.2),
)


def scale_xml(xml_text: str, factor: int) -> str:
    """Return a dump with ``factor`` copies of the original top-level nodes."""
    if factor < 1:
        raise ValueError("factor must be >= 1")
    root = ET.fromstring(xml_text)
    originals = [child for child in root if child.tag == "node"]
    for copy_number in range(1, factor):
        for original in originals:
            duplicate = copy.deepcopy(original)
            for element in duplicate.iter("node"):
                for name in RENAMED_ATTRIBUTES:
                    value = element.get(name, "")
                    if value:
                        element.set(name, "{}#c{}".format(value, copy_number))
            root.append(duplicate)
    return ET.tostring(root, encoding="unicode")


def _counts(nodes: Sequence[UiNode], attribute: str):
    counts = {}
    for node in nodes:
        value = getattr(node, attribute)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def make_selectors(nodes: Sequence[UiNode], count: int, seed: int) -> List[Tuple[str, Selector]]:
    """Generate ``count`` (kind, selector) pairs in the SELECTOR_MIX proportions."""
    rng = random.Random(seed)
    unique_pool: List[Selector] = []
    for attribute in ("resource_id", "text", "content_desc"):
        counts = _counts(nodes, attribute)
        unique_pool.extend(
            Selector(**{attribute: value}) for value, n in sorted(counts.items()) if n == 1
        )
    compound_pool = sorted(
        {(node.class_name, node.text) for node in nodes if node.text and node.class_name}
    )
    class_counts = _counts(nodes, "class_name")
    ambiguous_pool = sorted(value for value, n in class_counts.items() if n > 1)
    if not unique_pool or not compound_pool or not ambiguous_pool:
        raise ValueError("snapshot is too small to build the selector mix")

    selectors: List[Tuple[str, Selector]] = []
    for kind, share in SELECTOR_MIX:
        for i in range(round(count * share)):
            if kind == "unique":
                selector = rng.choice(unique_pool)
            elif kind == "compound":
                class_name, text = rng.choice(compound_pool)
                selector = Selector(class_name=class_name, text=text)
            elif kind == "ambiguous":
                selector = Selector(class_name=rng.choice(ambiguous_pool))
            else:
                selector = Selector(resource_id="missing:id/absent_{}_{}".format(seed, i))
            selectors.append((kind, selector))
    rng.shuffle(selectors)
    return selectors
