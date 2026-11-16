"""Locator (selector) validation against a UI snapshot.

A selector is a conjunction of exact attribute values, similar to
UIAutomator ``By`` criteria. Validation reports whether the selector
identifies exactly one element, several elements, or none.

Two interchangeable implementations are provided:

* ``NaiveValidator`` scans every node for each selector;
* ``IndexedValidator`` builds hash indexes once per snapshot and then
  filters only the smallest candidate list.

Both must return identical results; this is checked by the tests.
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .snapshot import UiNode

FOUND = "found"
AMBIGUOUS = "ambiguous"
ABSENT = "absent"

# Selector field name -> UiNode attribute name.
FIELDS = (
    ("resource_id", "resource_id"),
    ("text", "text"),
    ("content_desc", "content_desc"),
    ("class_name", "class_name"),
)


@dataclass(frozen=True)
class Selector:
    """Exact-match criteria; ``None`` means the field is not constrained."""

    resource_id: Optional[str] = None
    text: Optional[str] = None
    content_desc: Optional[str] = None
    class_name: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.criteria():
            raise ValueError("selector must constrain at least one field")

    def criteria(self) -> Tuple[Tuple[str, str], ...]:
        """Pairs (node attribute, expected value) for constrained fields."""
        return tuple(
            (attribute, getattr(self, field))
            for field, attribute in FIELDS
            if getattr(self, field) is not None
        )


@dataclass(frozen=True)
class ValidationResult:
    status: str
    matches: Tuple[int, ...]
    actionable: bool

    @property
    def is_valid(self) -> bool:
        """A locator is usable only if it is unique and actionable."""
        return self.status == FOUND and self.actionable


def _matches(node: UiNode, criteria: Sequence[Tuple[str, str]]) -> bool:
    return all(getattr(node, attribute) == value for attribute, value in criteria)


def _result(nodes: Sequence[UiNode], matches: List[int]) -> ValidationResult:
    if not matches:
        return ValidationResult(ABSENT, (), False)
    if len(matches) > 1:
        return ValidationResult(AMBIGUOUS, tuple(matches), False)
    node = nodes[matches[0]]
    return ValidationResult(FOUND, (node.index,), node.visible and node.enabled)


class NaiveValidator:
    """Baseline: linear scan of the whole hierarchy for every selector."""

    name = "naive"

    def __init__(self, nodes: Sequence[UiNode]) -> None:
        self.nodes = nodes

    def validate(self, selector: Selector) -> ValidationResult:
        criteria = selector.criteria()
        matches = [node.index for node in self.nodes if _matches(node, criteria)]
        return _result(self.nodes, matches)


class IndexedValidator:
    """Hash indexes per attribute, built once for a snapshot."""

    name = "indexed"

    def __init__(self, nodes: Sequence[UiNode]) -> None:
        self.nodes = nodes
        self._index: Dict[str, Dict[str, List[int]]] = {}
        for _, attribute in FIELDS:
            postings: Dict[str, List[int]] = defaultdict(list)
            for node in nodes:
                postings[getattr(node, attribute)].append(node.index)
            self._index[attribute] = dict(postings)

    def validate(self, selector: Selector) -> ValidationResult:
        criteria = selector.criteria()
        candidates = None
        for attribute, value in criteria:
            postings = self._index[attribute].get(value, [])
            if candidates is None or len(postings) < len(candidates):
                candidates = postings
            if not candidates:
                return _result(self.nodes, [])
        matches = [i for i in candidates if _matches(self.nodes[i], criteria)]
        return _result(self.nodes, matches)


VALIDATORS = {cls.name: cls for cls in (NaiveValidator, IndexedValidator)}
