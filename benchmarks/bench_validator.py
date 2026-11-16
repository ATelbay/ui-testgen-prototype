"""Microbenchmark of locator validation on real and scaled UI dumps.

Measured per snapshot, scale factor and implementation (naive / indexed):

* parse_ms  - parsing the XML dump into UiNode objects;
* build_ms  - constructing the validator (index build for ``indexed``);
* query_us  - mean latency of one selector in a batch of generated selectors.

Each configuration is warmed up and then timed ``--repeats`` times inside
one interpreter process; the whole measurement is replicated in
``--process-runs`` fresh processes to expose between-run variability.
Before timing, both implementations must return identical results.
"""
import argparse
import csv
import gc
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uitestgen.snapshot import parse_hierarchy  # noqa: E402
from uitestgen.validator import VALIDATORS  # noqa: E402
from uitestgen.workload import make_selectors, scale_xml  # noqa: E402

RAW_FIELDS = ["process_run", "snapshot", "scale", "nodes", "impl", "repeat",
              "parse_ms", "build_ms", "query_us"]


def percentile(values, q):
    """Nearest-rank percentile, q in (0, 100]."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[rank - 1]


def load_inputs(snapshot_dir, scales, queries, seed):
    inputs = []
    for path in sorted(Path(snapshot_dir).glob("*.xml")):
        xml_text = path.read_text(encoding="utf-8")
        base_nodes = parse_hierarchy(xml_text)
        selectors = [s for _, s in make_selectors(base_nodes, queries, seed)]
        for scale in scales:
            inputs.append((path.stem, scale, scale_xml(xml_text, scale), selectors))
    if not inputs:
        raise SystemExit("no *.xml snapshots in {}".format(snapshot_dir))
    return inputs


def check_equivalence(inputs):
    """Regression guard: all implementations agree on every selector.

    Returns the number of checked validations and the outcome counts.
    """
    checked = 0
    outcomes = {}
    for name, scale, xml_text, selectors in inputs:
        nodes = parse_hierarchy(xml_text)
        validators = [cls(nodes) for cls in VALIDATORS.values()]
        for selector in selectors:
            results = {v.validate(selector) for v in validators}
            if len(results) != 1:
                raise AssertionError("mismatch on {} x{}: {}".format(name, scale, selector))
            if scale == 1:
                status = results.pop().status
                outcomes[status] = outcomes.get(status, 0) + 1
            checked += 1
    return checked, outcomes


def time_once(xml_text, selectors, cls):
    t0 = time.perf_counter_ns()
    nodes = parse_hierarchy(xml_text)
    t1 = time.perf_counter_ns()
    validator = cls(nodes)
    t2 = time.perf_counter_ns()
    for selector in selectors:
        validator.validate(selector)
    t3 = time.perf_counter_ns()
    return len(nodes), (t1 - t0) / 1e6, (t2 - t1) / 1e6, (t3 - t2) / 1e3 / len(selectors)


def single_run(args, process_run):
    inputs = load_inputs(args.snapshots, args.scales, args.queries, args.seed)
    rows = []
    gc.disable()  # avoid collector pauses inside timed regions
    try:
        for name, scale, xml_text, selectors in inputs:
            for impl, cls in VALIDATORS.items():
                for _ in range(args.warmup):
                    time_once(xml_text, selectors, cls)
                for repeat in range(1, args.repeats + 1):
                    n, parse_ms, build_ms, query_us = time_once(xml_text, selectors, cls)
                    rows.append({"process_run": process_run, "snapshot": name, "scale": scale,
                                 "nodes": n, "impl": impl, "repeat": repeat,
                                 "parse_ms": round(parse_ms, 4), "build_ms": round(build_ms, 4),
                                 "query_us": round(query_us, 4)})
                gc.collect()
    finally:
        gc.enable()
    return rows


def memory_profile(args):
    """Traced memory (separate pass): parse peak and validator overhead."""
    rows = []
    for name, scale, xml_text, _ in load_inputs(args.snapshots, args.scales, args.queries, args.seed):
        gc.collect()
        tracemalloc.start()
        nodes = parse_hierarchy(xml_text)
        parse_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        for impl, cls in VALIDATORS.items():
            gc.collect()
            tracemalloc.start()
            validator = cls(nodes)
            retained = tracemalloc.get_traced_memory()[0]
            tracemalloc.stop()
            del validator
            rows.append({"snapshot": name, "scale": scale, "nodes": len(nodes), "impl": impl,
                         "parse_peak_kib": round(parse_peak / 1024.0, 1),
                         "validator_kib": round(retained / 1024.0, 1)})
        del nodes
    return rows


def summarize(raw_rows):
    groups = {}
    for row in raw_rows:
        groups.setdefault((row["scale"], row["impl"]), []).append(row)
    run_medians = {}
    for row in raw_rows:
        key = (row["scale"], row["impl"], row["process_run"])
        run_medians.setdefault(key, []).append(row["query_us"])
    summary = []
    for (scale, impl), rows in sorted(groups.items()):
        query = [r["query_us"] for r in rows]
        per_run = [statistics.median(v) for (s, i, _), v in run_medians.items()
                   if s == scale and i == impl]
        cv = (statistics.stdev(per_run) / statistics.mean(per_run) * 100.0
              if len(per_run) > 1 else 0.0)
        summary.append({
            "scale": scale, "impl": impl,
            "nodes_median": statistics.median(r["nodes"] for r in rows),
            "parse_ms_median": round(statistics.median(r["parse_ms"] for r in rows), 4),
            "build_ms_median": round(statistics.median(r["build_ms"] for r in rows), 4),
            "query_us_median": round(statistics.median(query), 3),
            "query_us_p95": round(percentile(query, 95), 3),
            "query_us_p99": round(percentile(query, 99), 3),
            "between_run_cv_pct": round(cv, 2),
            "samples": len(rows),
        })
    by_key = {(r["scale"], r["impl"]): r for r in summary}
    for row in summary:
        if row["impl"] != "indexed":
            continue
        naive = by_key[(row["scale"], "naive")]
        saved_us = naive["query_us_median"] - row["query_us_median"]
        extra_us = (row["build_ms_median"] - naive["build_ms_median"]) * 1000.0
        row["speedup_x"] = round(naive["query_us_median"] / row["query_us_median"], 1)
        row["break_even_queries"] = round(extra_us / saved_us, 2) if saved_us > 0 else ""
    return summary


def environment():
    def run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                                  timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    cpu = run(["sysctl", "-n", "machdep.cpu.brand_string"]) if sys.platform == "darwin" else \
        platform.processor()
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "git_commit": run(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(run(["git", "status", "--porcelain", "--", "src", "benchmarks"])),
    }


def relative(path):
    """Repository-relative path, so results do not expose local directories."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


def write_csv(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=ROOT / "data" / "snapshots")
    parser.add_argument("--scales", type=lambda s: [int(x) for x in s.split(",")],
                        default=[1, 2, 4, 8, 16, 32])
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--process-runs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "micro")
    parser.add_argument("--quick", action="store_true",
                        help="small smoke configuration for CI")
    parser.add_argument("--single-run", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.quick:
        args.scales, args.queries, args.repeats = [1, 4], 20, 3
        args.warmup, args.process_runs = 1, 2
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.single_run is not None:
        json.dump(single_run(args, args.single_run), sys.stdout)
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs(args.snapshots, args.scales, args.queries, args.seed)
    checked, outcomes = check_equivalence(inputs)
    print("equivalence check passed: {} selector validations".format(checked))
    print("outcomes at scale 1: {}".format(outcomes))

    passthrough = [a for a in (argv if argv is not None else sys.argv[1:])
                   if a not in ("--quick",)]
    if args.quick:
        passthrough += ["--scales", "1,4", "--queries", "20", "--repeats", "3", "--warmup", "1"]
    raw = []
    for run in range(1, args.process_runs + 1):
        completed = subprocess.run(
            [sys.executable, __file__, "--single-run", str(run)] + passthrough,
            capture_output=True, text=True, check=True)
        raw.extend(json.loads(completed.stdout))
        print("process run {}/{} done".format(run, args.process_runs))

    summary = summarize(raw)
    memory = memory_profile(args)
    write_csv(args.output / "raw.csv", raw, RAW_FIELDS)
    write_csv(args.output / "summary.csv", summary,
              list(summary[0]) + ["speedup_x", "break_even_queries"])
    write_csv(args.output / "memory.csv", memory)
    meta = {"config": {k: (relative(v) if isinstance(v, Path) else v)
                       for k, v in vars(args).items() if k != "single_run"},
            "equivalence_checked": checked, "outcomes_scale_1": outcomes,
            "environment": environment()}
    (args.output / "run.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    for row in summary:
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
