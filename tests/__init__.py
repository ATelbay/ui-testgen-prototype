"""Unit tests; make ``src`` importable without installing the package."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SNAPSHOTS = ROOT / "data" / "snapshots"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
