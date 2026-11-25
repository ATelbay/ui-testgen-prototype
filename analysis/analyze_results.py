"""Statistical analysis and figures for the practice 8 measurements (practice 10).

Reads only the committed raw data:

* results/macro/dump_latency.csv - 8 screens x 10 ``uiautomator dump`` runs;
* results/micro/raw.csv          - 8 screens x 6 scales x 2 implementations
                                   x 5 processes x 20 repeats;
* results/micro/run.json         - outcome counts and configuration.

The independent unit for inference is the screen (n = 8): repeats and
processes of one screen are not independent observations. The pooled dump
median uses all 80 runs with a two-level (screen, then repeat) bootstrap CI;
speedup, break-even q* and growth slopes start from per-screen medians.
Statistics use only the standard library;
figures need matplotlib (see analysis/requirements.txt) and are skipped with
``--no-figures``.

Usage (from the repository root):
    python analysis/analyze_results.py --output results/analysis
"""
import argparse
import collections
import csv
import json
import math
from pathlib import Path
import random
import statistics

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
BOOTSTRAP = 10000
# Two-sided 97.5 % quantile of Student's t for 7 degrees of freedom (n = 8 screens).
T_975_DF7 = 2.364624
LOCATORS_PER_STEP = 3  # as in the practice 8 step estimate


def read_csv(path):
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def quantile(values, q):
    """Linear-interpolation quantile (type 7, as in R and numpy defaults)."""
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def t_interval_log(values):
    """Geometric mean and 95 % t-interval computed on log values."""
    logs = [math.log(v) for v in values]
    mean = statistics.mean(logs)
    half = T_975_DF7 * statistics.stdev(logs) / math.sqrt(len(logs))
    return math.exp(mean), math.exp(mean - half), math.exp(mean + half)


def sign_test_two_sided(wins, n):
    """Exact two-sided sign test p-value for ``wins`` successes out of ``n``."""
    k = min(wins, n - wins)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


def slope(xs, ys):
    """Ordinary least squares slope and R^2."""
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    ss_res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return b, a, 1.0 - ss_res / ss_tot


# ---------------------------------------------------------------- snapshots

def analyze_macro(rows, rng):
    by_screen = collections.OrderedDict()
    for row in rows:
        by_screen.setdefault(row["screen"], []).append(row)
    dump = [float(r["dump_ms"]) for r in rows]
    pull = [float(r["pull_ms"]) for r in rows]

    # Hierarchical bootstrap of the pooled median: screens, then repeats.
    screens = list(by_screen)
    samples = []
    for _ in range(BOOTSTRAP):
        pooled = []
        for screen in rng.choices(screens, k=len(screens)):
            values = [float(r["dump_ms"]) for r in by_screen[screen]]
            pooled.extend(rng.choices(values, k=len(values)))
        samples.append(statistics.median(pooled))

    per_screen = []
    for screen, items in by_screen.items():
        values = [float(r["dump_ms"]) for r in items]
        q1, q3 = quantile(values, 0.25), quantile(values, 0.75)
        fence = q3 + 1.5 * (q3 - q1)
        sizes = collections.Counter(int(r["xml_bytes"]) for r in items)
        modal = sizes.most_common(1)[0][0]
        per_screen.append({
            "screen": screen,
            "n": len(values),
            "ok": sum(r["status"] == "ok" for r in items),
            "median_ms": statistics.median(values),
            "q1_ms": q1, "q3_ms": q3,
            "min_ms": min(values), "max_ms": max(values),
            "cv_pct": statistics.stdev(values) / statistics.mean(values) * 100.0,
            "outliers": [v for v in values if v > fence],
            "pull_median_ms": statistics.median(float(r["pull_ms"]) for r in items),
            "xml_sizes": dict(sizes),
            "changed_xml_dump_ms": [float(r["dump_ms"]) for r in items
                                    if int(r["xml_bytes"]) != modal],
        })
    medians = [s["median_ms"] for s in per_screen]
    return {
        "n": len(rows),
        "ok": sum(r["status"] == "ok" for r in rows),
        "dump_median_ms": statistics.median(dump),
        "dump_median_ci95_ms": [quantile(samples, 0.025), quantile(samples, 0.975)],
        "dump_p95_ms": quantile(dump, 0.95),
        "dump_max_ms": max(dump),
        "pull_median_ms": statistics.median(pull),
        "pull_p95_ms": quantile(pull, 0.95),
        "screen_median_range_ms": [min(medians), max(medians)],
        "per_screen": per_screen,
    }


# ------------------------------------------------------------ validator

def analyze_micro(rows, macro, rng):
    cells = collections.defaultdict(lambda: collections.defaultdict(list))
    nodes = {}
    for row in rows:
        key = (row["snapshot"], int(row["scale"]), row["impl"])
        for field in ("parse_ms", "build_ms", "query_us"):
            cells[key][field].append(float(row[field]))
        nodes[(row["snapshot"], int(row["scale"]))] = int(row["nodes"])
    med = {key: {f: statistics.median(v) for f, v in fields.items()}
           for key, fields in cells.items()}
    screens = sorted({k[0] for k in med})
    scales = sorted({k[1] for k in med})

    by_scale = []
    for scale in scales:
        speedups, q_star, wins = [], [], 0
        for s in screens:
            naive, indexed = med[(s, scale, "naive")], med[(s, scale, "indexed")]
            speedups.append(naive["query_us"] / indexed["query_us"])
            wins += indexed["query_us"] < naive["query_us"]
            saved = naive["query_us"] - indexed["query_us"]
            extra = (indexed["build_ms"] - naive["build_ms"]) * 1000.0
            q_star.append(extra / saved)
        gm, lo, hi = t_interval_log(speedups)
        pooled = {impl: statistics.median(v for (s, sc, i), c in cells.items()
                                          if sc == scale and i == impl
                                          for v in c["query_us"])
                  for impl in ("naive", "indexed")}
        by_scale.append({
            "scale": scale,
            "nodes_median": statistics.median(nodes[(s, scale)] for s in screens),
            "naive_us_pooled_median": pooled["naive"],
            "indexed_us_pooled_median": pooled["indexed"],
            "speedup_geomean": gm, "speedup_ci95": [lo, hi],
            "speedup_min": min(speedups), "speedup_max": max(speedups),
            "indexed_faster_screens": wins,
            "sign_test_p": sign_test_two_sided(wins, len(screens)),
            "q_star_median": statistics.median(q_star),
            "q_star_range": [min(q_star), max(q_star)],
        })

    # Growth exponent b in time ~ nodes^b: OLS on log10 values of the
    # per-screen medians; 95 % CI by a cluster bootstrap over screens.
    growth = {}
    for impl in ("naive", "indexed"):
        def fit(selected):
            xs = [math.log10(nodes[(s, sc)]) for s in selected for sc in scales]
            ys = [math.log10(med[(s, sc, impl)]["query_us"]) for s in selected for sc in scales]
            return slope(xs, ys)
        b, a, r2 = fit(screens)
        boot = []
        for _ in range(BOOTSTRAP):
            sample = rng.choices(screens, k=len(screens))
            if len(set(sample)) > 1:
                boot.append(fit(sample)[0])
        per_screen = [fit([s])[0] for s in screens]
        ratio = [med[(s, scales[-1], impl)]["query_us"] / med[(s, scales[0], impl)]["query_us"]
                 for s in screens]
        growth[impl] = {"pooled_slope": b, "pooled_intercept": a, "pooled_r2": r2,
                        "pooled_slope_ci95": [quantile(boot, 0.025), quantile(boot, 0.975)],
                        "screen_slope_range": [min(per_screen), max(per_screen)],
                        "growth_x32_over_x1_geomean": t_interval_log(ratio)[0]}

    # Step estimate per real screen: capture + in-process work for 3 locators.
    step = []
    capture = {s["screen"]: s for s in macro["per_screen"]}
    for s in screens:
        m = med[(s, 1, "indexed")]
        local_ms = m["parse_ms"] + m["build_ms"] + LOCATORS_PER_STEP * m["query_us"] / 1000.0
        capture_ms = capture[s]["median_ms"] + capture[s]["pull_median_ms"]
        step.append({"screen": s, "capture_ms": capture_ms, "local_ms": local_ms,
                     "local_share_pct": local_ms / (capture_ms + local_ms) * 100.0})

    # Between-process stability: sample CV of the 5 per-process medians.
    runs = collections.defaultdict(list)
    for row in rows:
        runs[(int(row["scale"]), row["impl"], int(row["process_run"]))].append(
            float(row["query_us"]))
    cv = []
    for scale in scales:
        for impl in ("naive", "indexed"):
            per_run = [statistics.median(v) for (sc, i, _), v in runs.items()
                       if sc == scale and i == impl]
            cv.append(statistics.stdev(per_run) / statistics.mean(per_run) * 100.0)

    points = [{"screen": s, "scale": sc, "impl": impl, "nodes": nodes[(s, sc)],
               "query_us": med[(s, sc, impl)]["query_us"]}
              for s in screens for sc in scales for impl in ("naive", "indexed")]
    return {"screens": len(screens), "by_scale": by_scale, "growth": growth,
            "step": step, "between_process_cv_pct": [min(cv), max(cv)],
            "points": points}


# --------------------------------------------------------------- figures

LABELS = {
    "ru": {"elements": "Число элементов в иерархии",
           "query": "Время проверки одного локатора, мкс",
           "dump": "Время uiautomator dump, мс",
           "naive": "naive (полный обход)", "indexed": "indexed (хеш-индекс)",
           "changed": "дамп с другим размером XML"},
    "en": {"elements": "UI elements in the hierarchy",
           "query": "Validation time per locator (µs)",
           "dump": "uiautomator dump time (ms)",
           "naive": "naive (full traversal)", "indexed": "indexed (hash index)",
           "changed": "dump with a different XML size"},
}
COLORS = {"naive": "#2a78d6", "indexed": "#eb6834"}  # validated categorical slots 1-2
MARKERS = {"naive": "o", "indexed": "s"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e1e0d9"


def _style(plt):
    plt.rcParams.update({
        "font.family": "Arial", "font.size": 8, "axes.labelsize": 8,
        "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.6,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "legend.fontsize": 7.5, "legend.frameon": False,
        "pdf.fonttype": 42, "ps.fonttype": 42, "savefig.dpi": 300,
    })


def _fmt_slope(lang, value):
    text = "{:.2f}".format(value)
    return ("наклон " + text.replace(".", ",")) if lang == "ru" else "slope " + text


def plot_scaling(ax, micro, lang):
    from matplotlib.ticker import FixedLocator, NullFormatter, NullLocator
    lab = LABELS[lang]
    for impl in ("naive", "indexed"):
        pts = [p for p in micro["points"] if p["impl"] == impl]
        ax.scatter([p["nodes"] for p in pts], [p["query_us"] for p in pts], s=10,
                   marker=MARKERS[impl], facecolor=COLORS[impl], edgecolor="white",
                   linewidth=0.4, zorder=3, label=lab[impl])
        g = micro["growth"][impl]
        xs = [30, 3000]
        ax.plot(xs, [10 ** (g["pooled_intercept"] + g["pooled_slope"] * math.log10(x)) for x in xs],
                color=COLORS[impl], linewidth=1.2, zorder=2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(30, 3000)
    ax.set_ylim(1, 1000)
    ax.xaxis.set_major_locator(FixedLocator([50, 100, 200, 500, 1000, 2000]))
    ax.xaxis.set_major_formatter(lambda v, _: "{:g}".format(v))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_major_formatter(lambda v, _: "{:g}".format(v))
    ax.grid(True, which="major", color=GRID, linewidth=0.5, zorder=0)
    ax.set_xlabel(lab["elements"])
    ax.set_ylabel(lab["query"])
    for impl, (x, dy) in {"naive": (700, 2.3), "indexed": (700, 0.42)}.items():
        g = micro["growth"][impl]
        y = 10 ** (g["pooled_intercept"] + g["pooled_slope"] * math.log10(x))
        ax.text(x, y * dy, _fmt_slope(lang, g["pooled_slope"]), color=INK, fontsize=7.5,
                ha="center", va="center")
    ax.legend(loc="upper left", handletextpad=0.3, borderaxespad=0.2, markerscale=1.5)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def plot_dumps(ax, macro, raw_rows, lang):
    lab = LABELS[lang]
    order = sorted(macro["per_screen"], key=lambda s: s["median_ms"])
    by_screen = collections.defaultdict(list)
    for row in raw_rows:
        by_screen[row["screen"]].append(row)
    jitter = random.Random(SEED)
    for x, info in enumerate(order):
        items = by_screen[info["screen"]]
        modal = max(info["xml_sizes"], key=info["xml_sizes"].get)
        for row in items:
            changed = int(row["xml_bytes"]) != modal
            ax.scatter(x + jitter.uniform(-0.18, 0.18), float(row["dump_ms"]), s=12,
                       marker="D" if changed else "o",
                       facecolor="white" if changed else COLORS["naive"],
                       edgecolor=COLORS["naive"], linewidth=0.8, zorder=3)
        ax.plot([x - 0.3, x + 0.3], [info["median_ms"]] * 2, color=INK, linewidth=1.4, zorder=4)
    ax.scatter([], [], s=12, marker="D", facecolor="white", edgecolor=COLORS["naive"],
               linewidth=0.8, label=lab["changed"])
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([s["screen"] for s in order], rotation=35, ha="right")
    ax.set_ylabel(lab["dump"])
    ax.set_ylim(1800, 3250)
    ax.grid(True, axis="y", color=GRID, linewidth=0.5, zorder=0)
    ax.legend(loc="center right", bbox_to_anchor=(1.0, 0.6), handletextpad=0.2,
              borderaxespad=0.2, markerscale=1.3)
    ax.yaxis.set_major_formatter(lambda v, _: "{:.0f}".format(v))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def make_figures(output, macro, micro, macro_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _style(plt)
    cm = 1 / 2.54
    # Two-panel figure for the Russian report (practice 10).
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(17 * cm, 6.6 * cm),
                                     gridspec_kw={"width_ratios": [1, 1.05]})
    plot_dumps(ax_a, macro, macro_rows, "ru")
    plot_scaling(ax_b, micro, "ru")
    for ax, letter in ((ax_a, "а"), (ax_b, "б")):
        ax.text(-0.25, 1.0, letter, transform=ax.transAxes, fontsize=9,
                fontweight="bold", va="bottom")
    fig.tight_layout(w_pad=2.0)
    for ext in ("png", "pdf"):
        fig.savefig(output / "fig_results_ru.{}".format(ext))
    plt.close(fig)
    # Single-column figure for the IEEE sample page (practice 12).
    fig, ax = plt.subplots(figsize=(3.45, 2.35))
    plot_scaling(ax, micro, "en")
    fig.tight_layout(pad=0.3)
    fig.savefig(output / "fig_scaling_en.pdf")
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "analysis")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    macro_rows = read_csv(ROOT / "results" / "macro" / "dump_latency.csv")
    micro_rows = read_csv(ROOT / "results" / "micro" / "raw.csv")
    run = json.loads((ROOT / "results" / "micro" / "run.json").read_text(encoding="utf-8"))
    macro = analyze_macro(macro_rows, rng)
    micro = analyze_micro(micro_rows, macro, rng)
    stats = {"seed": SEED, "bootstrap_resamples": BOOTSTRAP,
             "source_commit": run["environment"]["git_commit"],
             "outcomes_scale_1": run["outcomes_scale_1"],
             "macro": macro, "micro": {k: v for k, v in micro.items() if k != "points"}}
    (args.output / "stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (args.output / "validator_by_scale.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["scale", "nodes_median", "naive_us", "indexed_us", "speedup_geomean",
                         "speedup_ci95_low", "speedup_ci95_high", "speedup_min", "speedup_max",
                         "indexed_faster_screens", "sign_test_p", "q_star_median"])
        for r in micro["by_scale"]:
            writer.writerow([r["scale"], r["nodes_median"], round(r["naive_us_pooled_median"], 2),
                             round(r["indexed_us_pooled_median"], 2),
                             round(r["speedup_geomean"], 2), round(r["speedup_ci95"][0], 2),
                             round(r["speedup_ci95"][1], 2), round(r["speedup_min"], 2),
                             round(r["speedup_max"], 2), r["indexed_faster_screens"],
                             round(r["sign_test_p"], 4), round(r["q_star_median"], 2)])
    if not args.no_figures:
        make_figures(args.output, macro, micro, macro_rows)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
