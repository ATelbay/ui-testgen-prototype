"""Parsing of UIAutomator hierarchy dumps into a flat list of UI nodes.

The parser covers the XML format produced by ``adb shell uiautomator dump``.
Only the attributes needed for locator validation are kept.
"""
from dataclasses import dataclass
import re
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET

Bounds = Tuple[int, int, int, int]

_BOUNDS_RE = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")


class SnapshotError(ValueError):
    """Raised when a UI dump cannot be parsed."""


@dataclass(frozen=True)
class UiNode:
    """One element of the UI hierarchy in document (pre-order) order."""

    index: int
    parent: Optional[int]
    depth: int
    class_name: str
    package: str
    resource_id: str
    text: str
    content_desc: str
    clickable: bool
    enabled: bool
    bounds: Bounds

    @property
    def visible(self) -> bool:
        """True when the element occupies a non-empty screen area."""
        left, top, right, bottom = self.bounds
        return right > left and bottom > top


def parse_bounds(value: str) -> Bounds:
    """Convert ``[l,t][r,b]`` into a tuple of four integers."""
    match = _BOUNDS_RE.match(value.strip())
    if match is None:
        raise SnapshotError("invalid bounds: {!r}".format(value))
    left, top, right, bottom = (int(group) for group in match.groups())
    return left, top, right, bottom


def _flag(element: ET.Element, name: str) -> bool:
    return element.get(name, "false") == "true"


def parse_hierarchy(xml_text: str) -> List[UiNode]:
    """Return UI nodes of a UIAutomator dump in pre-order."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SnapshotError("malformed XML: {}".format(exc)) from exc
    if root.tag != "hierarchy":
        raise SnapshotError("root element must be <hierarchy>, got <{}>".format(root.tag))

    nodes: List[UiNode] = []
    stack = [(child, None, 0) for child in reversed(list(root)) if child.tag == "node"]
    while stack:
        element, parent, depth = stack.pop()
        index = len(nodes)
        nodes.append(
            UiNode(
                index=index,
                parent=parent,
                depth=depth,
                class_name=element.get("class", ""),
                package=element.get("package", ""),
                resource_id=element.get("resource-id", ""),
                text=element.get("text", ""),
                content_desc=element.get("content-desc", ""),
                clickable=_flag(element, "clickable"),
                enabled=_flag(element, "enabled"),
                bounds=parse_bounds(element.get("bounds", "[0,0][0,0]")),
            )
        )
        children = [child for child in element if child.tag == "node"]
        stack.extend((child, index, depth + 1) for child in reversed(children))
    return nodes


def load_snapshot(path) -> List[UiNode]:
    """Read and parse a UI dump stored in UTF-8."""
    with open(path, encoding="utf-8") as stream:
        return parse_hierarchy(stream.read())
