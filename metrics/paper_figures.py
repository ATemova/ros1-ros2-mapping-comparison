#!/usr/bin/env python3
"""Publication figures and LaTeX tables from report.json files.

Reads the report.json that make_report.py / compare_groups.py write for each batch
(results/reports/<tag>/report.json) and produces, per report:

  paper/tables/<name>.tex              booktabs table: mean ± 95% CI per group, difference
                                       to the baseline, p (Holm-adjusted when there are
                                       several comparisons) and Cliff's δ
  paper/figures/<name>_<metric>.pdf    one metric, per-run values per group (single column)
  paper/figures/<name>_overview.pdf    the selected metrics side by side (double column)
  paper/figures/<name>_effects.pdf     Cliff's δ of every comparison (single column)

plus .svg next to every .pdf, and paper/generated.json listing the outputs with the
SHA-256 of the report each one came from. Output is deterministic: the same report gives
byte-identical files, so regenerated figures only show up in a diff when the data changed.

  paper_figures.py --tags 20261201_matrix 20261202_rmw
  paper_figures.py --report results/reports/x/report.json --name main --all-metrics
  make paper-figures TAGS="20261201_matrix 20261202_rmw"

Figure widths: single column 3.5 in, double column 7.16 in (IEEE/ACM two-column).
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys

SINGLE_COL_IN = 3.5
DOUBLE_COL_IN = 7.16

# Metrics shown by default (those present in a report, in this order). --all-metrics
# puts every metric of the report in the table; --metrics picks an explicit list.
DEFAULT_METRICS = [
    "slam_cpu_mean",
    "slam_rss_peak_mb",
    "scan_to_map_latency_ms",
    "scan_to_map_latency_p95_ms",
    "tf_update_latency_ms",
    "map_period_jitter_ms",
    "time_to_first_map_s",
    "net_rate_kBps",
    "scan_drop_rate",
    "ate_rmse_m",
    "map_wall_f1",
    "map_cell_accuracy",
    "cpu_mean",
    "mem_peak_mb",
]

# Okabe-Ito, colour-blind safe. Known groups keep the same colour in every figure.
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000"]
KNOWN_COLORS = {
    "ros1": "#0072B2", "tcpros": "#0072B2", "noetic": "#0072B2", "ros1-noetic": "#0072B2",
    "ros2": "#D55E00", "rmw_fastrtps_cpp": "#D55E00", "humble": "#D55E00", "ros2-humble-fastrtps": "#D55E00",
    "rmw_cyclonedds_cpp": "#009E73", "ros2-humble-cyclonedds": "#009E73",
    "rmw_zenoh_cpp": "#CC79A7", "ros2-humble-zenoh": "#CC79A7",
    "jazzy": "#E69F00", "ros2-jazzy-fastrtps": "#E69F00",
    "ros2-jazzy-cyclonedds": "#56B4E9", "ros2-jazzy-zenoh": "#000000",
}
NAMES = {
    "ros1": "ROS 1", "ros2": "ROS 2", "noetic": "Noetic", "humble": "Humble", "jazzy": "Jazzy",
    "tcpros": "TCPROS", "fastrtps": "Fast DDS", "cyclonedds": "Cyclone DDS", "zenoh": "Zenoh",
    "rmw_fastrtps_cpp": "Fast DDS", "rmw_cyclonedds_cpp": "Cyclone DDS", "rmw_zenoh_cpp": "Zenoh",
    "default": "Unconstrained", "amd64": "amd64", "arm64": "arm64",
    "slam_toolbox": "slam_toolbox", "gmapping": "GMapping",
}
# Cliff's δ thresholds (Romano et al. 2006): negligible < 0.147 ≤ small < 0.33 ≤ medium < 0.474 ≤ large
DELTA_SMALL, DELTA_MEDIUM, DELTA_LARGE = 0.147, 0.33, 0.474


# ---------------------------------------------------------------- naming
def display_name(group):
    """Readable group name: ros2-humble-cyclonedds -> ROS 2 Humble / Cyclone DDS."""
    if group in NAMES:
        return NAMES[group]
    m = re.fullmatch(r"(ros[12])-([a-z]+)(?:-([a-z0-9_]+))?", group)
    if m:
        stack, distro, rmw = m.groups()
        s = f"{NAMES[stack]} {NAMES.get(distro, distro.capitalize())}"
        return f"{s} / {NAMES.get(rmw, rmw)}" if rmw else s
    return group


def slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "report"


def assign_colors(groups):
    colors, spare = {}, [c for c in PALETTE if c not in KNOWN_COLORS.values()] + PALETTE
    i = 0
    for g in groups:
        if g in KNOWN_COLORS:
            colors[g] = KNOWN_COLORS[g]
    for g in sorted(set(groups) - set(colors)):
        used = set(colors.values())
        while spare[i % len(spare)] in used and i < 2 * len(spare):
            i += 1
        colors[g] = spare[i % len(spare)]
        i += 1
    return colors


# ---------------------------------------------------------------- LaTeX
_TEX_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
                "→": r"$\rightarrow$", "±": r"$\pm$", "δ": r"$\delta$", "µ": r"$\mu$", "–": "--", "—": "---"}


def tex(text):
    return "".join(_TEX_SPECIAL.get(ch, ch) for ch in str(text))


def finite(v):
    return v is not None and isinstance(v, (int, float)) and v == v and not math.isinf(v)


def digits_for(values):
    scale = max([abs(v) for v in values if finite(v)] + [0.0])
    return 2 if scale >= 10 or scale == 0 else 3 if scale >= 1 else 4


def num(v, d, signed=False):
    if not finite(v):
        return "n/a"
    s = f"{v:+.{d}f}" if signed else f"{v:.{d}f}"
    return s.replace("-", "$-$").replace("+", "$+$")


def p_text(p):
    if not finite(p):
        return "n/a"
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


def metric_label(row):
    return f"{row['label']} ({row['unit']})" if row.get("unit") else row["label"]


def table_tex(report, rows, name, caption=None, float_env=True):
    order, base = report["groups"], report["baseline"]
    k = len(order)
    holm = any("p_holm" in c for r in rows for c in r["comparisons"])
    kw = k > 2 and any("kruskal_wallis" in r for r in rows)
    ncols = 2 + (3 if k > 1 else 0) + (1 if kw else 0)
    cols = "lr" + ("rrr" if k > 1 else "") + ("r" if kw else "")
    head = ["", r"Mean $\pm$ 95\,\% CI"]
    if k > 1:
        head += [r"$\Delta$ (\%)", r"$p_{\mathrm{Holm}}$" if holm else "$p$", r"$\delta$"]
    if kw:
        head.append(r"$p_{\mathrm{KW}}$")

    body = []
    for i, r in enumerate(rows):
        d = digits_for([r["groups"][g]["mean"] for g in order])
        comps = {c["group"]: c for c in r["comparisons"]}
        first = f"\\multicolumn{{{ncols - (1 if kw else 0)}}}{{l}}{{\\textit{{{tex(metric_label(r))}}}}}"
        if kw:
            first += " & " + p_text(r.get("kruskal_wallis", {}).get("p"))
        body.append(first + r" \\")
        for g in order:
            st = r["groups"][g]
            cells = [r"\quad " + tex(display_name(g)), f"{num(st['mean'], d)} $\\pm$ {num(st['ci95'], d)}"]
            if k > 1:
                if g == base:
                    cells += ["---", "---", "---"]
                else:
                    c = comps.get(g, {})
                    pct = c.get("diff_pct")
                    diff = num(c.get("diff"), d, signed=True)
                    if finite(pct):
                        diff += f" ({num(pct, 1, signed=True)})"
                    cells += [diff, p_text(c.get("p_holm", c.get("p_value"))), num(c.get("cliffs_delta"), 2, signed=True)]
            if kw:
                cells.append("")
            body.append(" & ".join(cells) + r" \\")
        if i < len(rows) - 1:
            body.append(r"\addlinespace")

    ns = sorted({len(report["runs"][g]) for g in order})
    n_text = f"$n={ns[0]}$" if len(ns) == 1 else "$n=" + "$--$".join(str(x) for x in (ns[0], ns[-1])) + "$"
    cond = report.get("condition", {})
    where = ", ".join(f"{tex(key.replace('_', ' '))}: \\texttt{{{tex(cond[key])}}}"
                      for key in ("bag_id", "rate", "condition") if cond.get(key) not in (None, ""))
    if caption is None:
        caption = (" vs.\\ ".join(tex(display_name(g)) for g in order) if k <= 4
                   else f"{k} groups by {tex(report['group_by'])}")
        caption += f". Mean $\\pm$ 95\\,\\% CI over {n_text} runs per group"
        if k > 1:
            caption += (f"; $\\Delta$: difference to {tex(display_name(base))} (in \\%), two-sided Mann--Whitney $U$ "
                        + ("$p$ (Holm-adjusted across the comparisons of a metric)" if holm else "$p$")
                        + r" and Cliff's $\delta$ ($>0$: higher than the baseline)")
            if kw:
                caption += r"; $p_{\mathrm{KW}}$: Kruskal--Wallis across all groups"
        caption += f" ({where})." if where else "."
    else:
        caption = tex(caption)

    lines = [f"% Generated by metrics/paper_figures.py from report.json ({name}). Do not edit by hand.",
             r"% Needs \usepackage{booktabs}."]
    if float_env:
        lines += [r"\begin{table*}[t]" if k > 2 else r"\begin{table}[t]", r"\centering", r"\small",
                  f"\\caption{{{caption}}}", f"\\label{{tab:{name}}}"]
    lines += [f"\\begin{{tabular}}{{{cols}}}", r"\toprule", " & ".join(head) + r" \\", r"\midrule"]
    lines += body
    lines += [r"\bottomrule", r"\end{tabular}"]
    if float_env:
        lines.append(r"\end{table*}" if k > 2 else r"\end{table}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- figures
def setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["DejaVu Serif"],
        "mathtext.fontset": "dejavuserif",
        "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.linewidth": 0.4, "grid.alpha": 0.4,
        "lines.linewidth": 0.8,
        "pdf.fonttype": 42, "ps.fonttype": 42,     # embed TrueType, no Type 3 fonts
        "svg.fonttype": "none", "svg.hashsalt": "paper-figures",
        "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    })
    return plt


def save(fig, base, formats, outputs):
    for ext in formats:
        path = f"{base}.{ext}"
        meta = {"Creator": None, "Producer": None, "CreationDate": None} if ext == "pdf" else \
               {"Creator": None, "Date": None} if ext == "svg" else {}
        fig.savefig(path, format=ext, metadata=meta, **({"dpi": 300} if ext == "png" else {}))
        outputs.append(path)


def strip_box(ax, row, order, colors, seed, rotate=None):
    rng = random.Random(seed)
    data = [[v for v in row["groups"][g]["values"] if finite(v)] for g in order]
    pos = list(range(1, len(order) + 1))
    if any(data):
        bp = ax.boxplot([d if d else [float("nan")] for d in data], positions=pos, widths=0.5,
                        showfliers=False, patch_artist=True, medianprops={"color": "black", "linewidth": 0.9},
                        whiskerprops={"linewidth": 0.6}, capprops={"linewidth": 0.6}, boxprops={"linewidth": 0.6})
        for patch, g in zip(bp["boxes"], order):
            patch.set_facecolor(colors[g])
            patch.set_alpha(0.25)
    for x, g, d in zip(pos, order, data):
        xs = [x + rng.uniform(-0.12, 0.12) for _ in d]
        ax.scatter(xs, d, s=9, color=colors[g], edgecolors="white", linewidths=0.3, zorder=3)
    ax.set_xticks(pos)
    if rotate is None:
        rotate = len(order) > 3
    ax.set_xticklabels([display_name(g) for g in order], rotation=25 if rotate else 0,
                       ha="right" if rotate else "center", rotation_mode="anchor")
    ax.set_xlim(0.4, len(order) + 0.6)
    ax.set_ylabel(row["unit"] or "value")
    ax.set_title(row["label"])


def metric_figure(plt, row, order, colors, base, formats, outputs):
    width = SINGLE_COL_IN if len(order) <= 4 else DOUBLE_COL_IN / 2 * 1.4
    fig, ax = plt.subplots(figsize=(width, 2.3))
    strip_box(ax, row, order, colors, seed=row["metric"])
    save(fig, base, formats, outputs)
    plt.close(fig)


def overview_figure(plt, rows, order, colors, base, formats, outputs, ncols=4):
    n = len(rows)
    ncols = min(ncols, n)
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(DOUBLE_COL_IN, 1.9 * nrows), squeeze=False)
    for ax, row in zip(axes.flat, rows):
        strip_box(ax, row, order, colors, seed=row["metric"],
                  rotate=len(order) > 2 or any(len(display_name(g)) > 10 for g in order))
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    fig.tight_layout(w_pad=1.0, h_pad=1.0)
    save(fig, base, formats, outputs)
    plt.close(fig)


def effects_figure(plt, rows, order, base_group, colors, base, formats, outputs):
    comps = order[1:]
    if not comps:
        return
    n = len(rows)
    fig, ax = plt.subplots(figsize=(SINGLE_COL_IN, 0.6 + 0.22 * n))
    ax.axvspan(-DELTA_SMALL, DELTA_SMALL, color="0.9", zorder=0, linewidth=0)
    for t in (DELTA_MEDIUM, DELTA_LARGE):
        for s in (-1, 1):
            ax.axvline(s * t, color="0.6", linewidth=0.5, linestyle=":", zorder=1)
    ax.axvline(0, color="0.3", linewidth=0.6, zorder=1)
    step = 0.5 / max(len(comps), 1)
    for ci, g in enumerate(comps):
        off = (ci - (len(comps) - 1) / 2) * step
        for i, row in enumerate(rows):
            c = next((c for c in row["comparisons"] if c["group"] == g), None)
            if c is None or not finite(c.get("cliffs_delta")):
                continue
            p = c.get("p_holm", c.get("p_value"))
            sig = finite(p) and p < 0.05
            ax.scatter([c["cliffs_delta"]], [n - 1 - i + off], s=16, marker="o", zorder=3,
                       color=colors[g] if sig else "white", edgecolors=colors[g], linewidths=0.9)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r["label"] for r in reversed(rows)])
    ax.set_xlim(-1.05, 1.05)
    ax.set_xticks([-1, -0.5, 0, 0.5, 1])
    ax.set_ylim(-0.6, n - 0.4)
    ax.grid(False)
    ax.set_xlabel(f"Cliff's δ vs {display_name(base_group)}  (filled: p < 0.05)")
    if len(comps) > 1:
        from matplotlib.lines import Line2D
        handles = [Line2D([], [], marker="o", linestyle="", markersize=4, color=colors[g], label=display_name(g))
                   for g in comps]
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.18 - 0.6 / max(n, 1)), ncol=min(len(comps), 3),
                  frameon=False, handletextpad=0.3, columnspacing=1.0)
    save(fig, base, formats, outputs)
    plt.close(fig)


# ---------------------------------------------------------------- driver
def select_rows(report, metrics, all_metrics):
    by_key = {r["metric"]: r for r in report["metrics"]}
    if metrics:
        missing = [m for m in metrics if m not in by_key]
        if missing:
            print(f"warning: not in report: {', '.join(missing)}", file=sys.stderr)
        return [by_key[m] for m in metrics if m in by_key]
    if all_metrics:
        return list(report["metrics"])
    return [by_key[m] for m in DEFAULT_METRICS if m in by_key]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def generate(report_path, name, out, formats, metrics=None, all_metrics=False, figure_metrics=None,
             caption=None, float_env=True, figures=True):
    with open(report_path) as f:
        report = json.load(f)
    for key in ("groups", "baseline", "metrics", "runs"):
        if key not in report:
            raise ValueError(f"{report_path}: not a compare_groups report (no '{key}')")
    rows = select_rows(report, metrics, all_metrics)
    if not rows:
        raise ValueError(f"{report_path}: none of the selected metrics are in the report")
    order = report["groups"]
    colors = assign_colors(order)
    tables = os.path.join(out, "tables")
    figs = os.path.join(out, "figures")
    os.makedirs(tables, exist_ok=True)
    outputs = []

    tpath = os.path.join(tables, f"{name}.tex")
    with open(tpath, "w") as f:
        f.write(table_tex(report, rows, name, caption=caption, float_env=float_env))
    outputs.append(tpath)

    if figures:
        os.makedirs(figs, exist_ok=True)
        plt = setup_matplotlib()
        fig_rows = rows if figure_metrics is None else [r for r in rows if r["metric"] in figure_metrics]
        if all_metrics and figure_metrics is None and not metrics:
            fig_rows = [r for r in rows if r["metric"] in DEFAULT_METRICS] or rows[:8]
        for row in fig_rows:
            metric_figure(plt, row, order, colors, os.path.join(figs, f"{name}_{row['metric']}"), formats, outputs)
        if fig_rows:
            overview_figure(plt, fig_rows[:8], order, colors, os.path.join(figs, f"{name}_overview"), formats, outputs)
        if len(order) > 1:
            effects_figure(plt, rows, order, report["baseline"], colors,
                           os.path.join(figs, f"{name}_effects"), formats, outputs)
    return {"name": name, "report": report_path, "report_sha256": sha256(report_path),
            "group_by": report.get("group_by"), "groups": order, "baseline": report["baseline"],
            "metrics": [r["metric"] for r in rows],
            "outputs": sorted(os.path.relpath(p, out) for p in outputs)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Publication figures (PDF/SVG) and LaTeX tables from report.json.")
    src = ap.add_argument_group("input (at least one)")
    src.add_argument("--tags", nargs="+", default=[], help="run tags; reads <reports>/<tag>/report.json")
    src.add_argument("--report", action="append", default=[], help="path to a report.json (repeatable)")
    ap.add_argument("--reports", default="results/reports", help="reports directory for --tags")
    ap.add_argument("--name", action="append", default=[],
                    help="output name per input, in order (default: the tag, or the report's folder name)")
    ap.add_argument("--out", default="paper", help="writes <out>/figures and <out>/tables (default paper)")
    ap.add_argument("--formats", default="pdf,svg", help="comma-separated: pdf, svg, png (default pdf,svg)")
    ap.add_argument("--metrics", help="comma-separated metric keys for tables and figures (default: a curated set)")
    ap.add_argument("--all-metrics", action="store_true", help="every metric of the report in the table")
    ap.add_argument("--caption", help="table caption (default: generated from the report)")
    ap.add_argument("--no-float", action="store_true", help="write only the tabular, without table environment")
    ap.add_argument("--tables-only", action="store_true", help="skip figures (no matplotlib needed)")
    args = ap.parse_args(argv)

    inputs = [(os.path.join(args.reports, t.replace(",", "+"), "report.json"), slug(t.replace(",", "+")))
              for t in args.tags]
    inputs += [(p, slug(os.path.basename(os.path.dirname(os.path.abspath(p))))) for p in args.report]
    if not inputs:
        ap.error("give --tags and/or --report")
    if args.name:
        if len(args.name) != len(inputs):
            ap.error(f"--name given {len(args.name)} times for {len(inputs)} input(s)")
        inputs = [(p, slug(n)) for (p, _), n in zip(inputs, args.name)]
    names = [n for _, n in inputs]
    if len(set(names)) != len(names):
        ap.error(f"duplicate output names {names}; use --name")
    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    bad = [f for f in formats if f not in ("pdf", "svg", "png")]
    if bad:
        ap.error(f"unsupported format(s): {', '.join(bad)}")
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()] if args.metrics else None

    entries, failed = [], 0
    for path, name in inputs:
        if not os.path.isfile(path):
            print(f"{path}: not found (run `make report TAG=...` first)", file=sys.stderr)
            failed += 1
            continue
        try:
            e = generate(path, name, args.out, formats, metrics=metrics, all_metrics=args.all_metrics,
                         caption=args.caption, float_env=not args.no_float, figures=not args.tables_only)
        except (ValueError, KeyError) as ex:
            print(f"{path}: {ex}", file=sys.stderr)
            failed += 1
            continue
        entries.append(e)
        print(f"{name}: {len(e['outputs'])} file(s) from {path}")

    os.makedirs(args.out, exist_ok=True)
    index = os.path.join(args.out, "generated.json")
    existing = {}
    if os.path.isfile(index):
        try:
            with open(index) as f:
                existing = {e["name"]: e for e in json.load(f).get("reports", [])}
        except (OSError, ValueError, KeyError, TypeError):
            existing = {}
    existing.update({e["name"]: e for e in entries})
    with open(index, "w") as f:
        json.dump({"generator": "metrics/paper_figures.py", "reports": [existing[k] for k in sorted(existing)]},
                  f, indent=2)
        f.write("\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
