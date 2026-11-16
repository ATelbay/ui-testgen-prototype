"""Prototype components of the LLM-based Android UI test generation framework."""

from .snapshot import SnapshotError, UiNode, load_snapshot, parse_hierarchy
from .validator import (
    ABSENT,
    AMBIGUOUS,
    FOUND,
    IndexedValidator,
    NaiveValidator,
    Selector,
    ValidationResult,
)

__version__ = "0.1.0"

__all__ = [
    "ABSENT",
    "AMBIGUOUS",
    "FOUND",
    "IndexedValidator",
    "NaiveValidator",
    "Selector",
    "SnapshotError",
    "UiNode",
    "ValidationResult",
    "load_snapshot",
    "parse_hierarchy",
]
