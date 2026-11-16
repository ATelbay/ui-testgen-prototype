import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests import ROOT


class BenchmarkSmokeTest(unittest.TestCase):
    """The benchmark must run end to end; timings are not asserted."""

    def test_quick_benchmark_writes_summary_for_both_implementations(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, str(ROOT / "benchmarks" / "bench_validator.py"),
                 "--quick", "--output", tmp],
                check=True, capture_output=True, text=True, timeout=300)
            with (Path(tmp) / "summary.csv").open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({row["impl"] for row in rows}, {"naive", "indexed"})
            self.assertEqual({row["scale"] for row in rows}, {"1", "4"})
            for row in rows:
                self.assertGreater(float(row["query_us_median"]), 0.0)


if __name__ == "__main__":
    unittest.main()
