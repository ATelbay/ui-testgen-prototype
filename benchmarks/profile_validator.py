"""Profile one validation step with cProfile (the Python analogue of perf/gprof).

The step parses the largest scaled snapshot, builds the validator and checks
the generated selectors. The top functions by cumulative time are written
to ``results/profile/<impl>.txt``.
"""
import argparse
import cProfile
import io
from pathlib import Path
import pstats
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uitestgen.snapshot import parse_hierarchy  # noqa: E402
from uitestgen.validator import VALIDATORS  # noqa: E402
from uitestgen.workload import make_selectors, scale_xml  # noqa: E402


def step(xml_text, selectors, cls, rounds):
    for _ in range(rounds):
        validator = cls(parse_hierarchy(xml_text))
        for selector in selectors:
            validator.validate(selector)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path,
                        default=ROOT / "data" / "snapshots" / "settings_main.xml")
    parser.add_argument("--scale", type=int, default=32)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "profile")
    args = parser.parse_args(argv)

    xml_text = args.snapshot.read_text(encoding="utf-8")
    selectors = [s for _, s in make_selectors(parse_hierarchy(xml_text), args.queries, args.seed)]
    scaled = scale_xml(xml_text, args.scale)
    args.output.mkdir(parents=True, exist_ok=True)
    for impl, cls in VALIDATORS.items():
        profiler = cProfile.Profile()
        profiler.enable()
        step(scaled, selectors, cls, args.rounds)
        profiler.disable()
        buffer = io.StringIO()
        stats = pstats.Stats(profiler, stream=buffer)
        stats.strip_dirs().sort_stats("cumulative").print_stats(args.top)
        header = "# {} x{}, {} selectors, {} rounds\n".format(
            args.snapshot.name, args.scale, len(selectors), args.rounds)
        (args.output / (impl + ".txt")).write_text(header + buffer.getvalue(), encoding="utf-8")
        print("profile written:", args.output / (impl + ".txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
