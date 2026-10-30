#!/usr/bin/env python3
"""Generate a markdown report with tables and figures for a batch of runs.

    make_report.py --tag T [--group-by stack|rmw|ros_distro|variant|condition] [--baseline G]
                   [--out results/reports/T] [--latest results/report.md]

Writes into --out:
    report.md            setup, statistics, figures, map consistency, provenance, run list
    stats.md / report.json / runs.csv     from compare_groups.py
    map_consistency.md / .json            from map_quality.py
    figures/*.png        metric box plots, SLAM CPU/RSS over time, trajectories, maps
--latest also writes a copy (figure links adjusted) e.g. results/report.md.
Figures need matplotlib (and numpy); without them the report has tables only.
"""

import argparse
import csv
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir))
sys.path.insert(0, HERE)

FIGURE_METRICS = [
    ("slam_cpu_mean", "SLAM CPU mean (% core)"),
    ("cpu_mean", "System CPU mean (%)"),
    ("slam_rss_peak_mb", "SLAM RSS peak (MB)"),
    ("scan_to_map_latency_ms", "Scan→map latency (ms)"),
    ("tf_update_latency_ms", "Scan→TF latency (ms)"),
    ("map_period_jitter_ms", "Map jitter (ms)"),
    ("ate_rmse_m", "ATE RMSE (m)"),
    ("map_wall_f1", "Wall F1 vs reference"),
    ("net_rate_kBps", "Network (kB/s)"),
    ("scan_drop_rate", "Scan drop rate"),
    ("slam_rss_slope_mb_per_min", "SLAM RSS trend (MB/min)"),
    ("middleware_cpu_mean", "Middleware CPU (% core)"),
]


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_runs_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- figures
def figures(rows, groups, out_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return [], "matplotlib/numpy not available; figures skipped."

    fig_dir = os.path.join(out_dir, "figures")
    os.makedirs(fig_dir, exist_ok=True)
    made = []
    by_group = {g: [r for r in rows if r["group"] == g] for g in groups}
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    # 1. per-metric distributions
    metrics = [(k, t) for k, t in FIGURE_METRICS
               if all(fnum(r.get(k)) is not None for r in rows) and rows]
    if metrics:
        n = len(metrics)
        cols = 3 if n > 4 else n
        nrows = (n + cols - 1) // cols
        fig, axes = plt.subplots(nrows, cols, figsize=(4.2 * cols, 3.2 * nrows), squeeze=False)
        rng = np.random.RandomState(0)
        for ax, (key, title) in zip(axes.ravel(), metrics):
            data = [[fnum(r[key]) for r in by_group[g]] for g in groups]
            ax.boxplot(data, widths=0.5, showfliers=False, medianprops={"color": "black"})
            for i, vals in enumerate(data):
                ax.scatter(i + 1 + rng.uniform(-0.12, 0.12, len(vals)), vals, s=14,
                           color=colors[i % len(colors)], zorder=3)
            ax.set_xticks(range(1, len(groups) + 1))
            ax.set_xticklabels(groups, rotation=20, ha="right", fontsize=8)
            ax.set_title(title, fontsize=10)
            ax.grid(True, axis="y", alpha=0.3)
        for ax in axes.ravel()[n:]:
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(os.path.join(fig_dir, "metrics.png"), dpi=130)
        plt.close(fig)
        made.append(("metrics.png", "Per-run values by group (box: quartiles, dots: runs)"))

    # 2. SLAM CPU and RSS over time (mean across runs of each group)
    def series(run_dir, role="slam"):
        path = os.path.join(run_dir, "proc_metrics.csv")
        if not os.path.exists(path):
            return None
        t, cpu, rss = [], [], []
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                if r.get("role") == role and int(r.get("n_procs") or 0) > 0:
                    t.append(float(r["elapsed_time_sec"]))
                    cpu.append(float(r["cpu_percent"]))
                    rss.append(float(r["rss_mb"]))
        return (t, cpu, rss) if t else None

    traces = {g: [s for s in (series(r["run_dir"]) for r in by_group[g]) if s] for g in groups}
    if any(traces.values()):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.4))
        for i, g in enumerate(groups):
            tr = traces[g]
            if not tr:
                continue
            n = min(len(s[0]) for s in tr)
            t = np.array(tr[0][0][:n]) - tr[0][0][0]
            for idx, ax in ((1, a1), (2, a2)):
                m = np.mean([s[idx][:n] for s in tr], axis=0)
                ax.plot(t, m, label=f"{g} (n={len(tr)})", color=colors[i % len(colors)], lw=1.3)
        a1.set_title("SLAM process CPU (mean over runs)", fontsize=10)
        a1.set_ylabel("% of one core")
        a2.set_title("SLAM process RSS (mean over runs)", fontsize=10)
        a2.set_ylabel("MB")
        for ax in (a1, a2):
            ax.set_xlabel("time since SLAM start (s)")
            ax.grid(True, alpha=0.3)
        a1.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(fig_dir, "slam_timeline.png"), dpi=130)
        plt.close(fig)
        made.append(("slam_timeline.png", "SLAM process CPU and memory over the run"))

    # 3. trajectories (first run of each group) against the reference
    def tum_xy(path):
        xs, ys = [], []
        with open(path) as f:
            for line in f:
                v = line.split()
                if len(v) == 8:
                    xs.append(float(v[1]))
                    ys.append(float(v[2]))
        return xs, ys

    first = {g: by_group[g][0]["run_dir"] for g in groups if by_group[g]}
    trajs = {g: os.path.join(d, "trajectory.tum") for g, d in first.items()
             if os.path.exists(os.path.join(d, "trajectory.tum"))}
    if trajs:
        fig, ax = plt.subplots(figsize=(6, 5))
        ref = None
        for d in first.values():
            m = read_json(os.path.join(d, "run_metrics.json")) or {}
            ref = (m.get("trajectory") or {}).get("reference") or ref
        if ref and os.path.exists(ref):
            x, y = tum_xy(ref)
            ax.plot(x, y, color="black", lw=2.2, alpha=0.35, label="reference")
        for i, (g, p) in enumerate(trajs.items()):
            x, y = tum_xy(p)
            ax.plot(x, y, color=colors[i % len(colors)], lw=1.2, label=g)
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        ax.set_title("Online trajectory, first run of each group", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(fig_dir, "trajectories.png"), dpi=130)
        plt.close(fig)
        made.append(("trajectories.png", "Estimated trajectories (unaligned, map frame)"))

    # 4. maps (first run of each group)
    maps = {g: os.path.join(d, "map.yaml") for g, d in first.items() if os.path.exists(os.path.join(d, "map.yaml"))}
    if maps:
        from map_quality import load_map
        fig, axes = plt.subplots(1, len(maps), figsize=(4.2 * len(maps), 4), squeeze=False)
        for ax, (g, p) in zip(axes.ravel(), maps.items()):
            m = load_map(p)
            img = np.full(m["cls"].shape, 0.8)
            img[m["cls"] == 0] = 1.0
            img[m["cls"] == 1] = 0.0
            ax.imshow(img, cmap="gray", vmin=0, vmax=1, interpolation="nearest")
            ax.set_title(g, fontsize=10)
            ax.axis("off")
        fig.tight_layout()
        fig.savefig(os.path.join(fig_dir, "maps.png"), dpi=130)
        plt.close(fig)
        made.append(("maps.png", "Saved maps, first run of each group"))
    return made, None


# ---------------------------------------------------------------- provenance
def provenance(rows, groups):
    per_group = {}
    commits, dirty, bags, configs, hosts = set(), False, set(), set(), set()
    for r in rows:
        man = read_json(os.path.join(r["run_dir"], "run_manifest.json")) or {}
        meta = read_json(os.path.join(r["run_dir"], "run_meta.json")) or {}
        git = man.get("git") or meta.get("git") or {}
        if git.get("commit"):
            commits.add(git["commit"][:12])
        dirty = dirty or bool(git.get("dirty"))
        inp = man.get("inputs") or {}
        if inp.get("bag"):
            bags.add(inp["bag"]["sha256"][:16])
        if inp.get("params"):
            configs.add(inp["params"]["sha256"][:16])
        host = man.get("host") or meta.get("host") or {}
        hosts.add(f"{host.get('cpu_model')} ({host.get('cpu_count') or (host.get('limits') or {}).get('cpu_count')} CPUs)")
        g = per_group.setdefault(r["group"], {"images": set(), "distro": set(), "rmw": set(),
                                               "slam_toolbox": set(), "condition": set()})
        img = man.get("image") or {}
        if img.get("tag"):
            g["images"].add(f"{img['tag']} {(img.get('id') or '')[7:19]}".strip())
        sw = man.get("software") or {}
        g["distro"].add(str(sw.get("ros_distro") or meta.get("ros_distro")))
        g["rmw"].add(str(r.get("rmw")))
        v = (sw.get("ros_packages") or {}).get("slam-toolbox")
        if v:
            g["slam_toolbox"].add(v)
        g["condition"].add(str(r.get("condition")))
    return {"per_group": per_group, "commits": commits, "dirty": dirty, "bags": bags,
            "configs": configs, "hosts": hosts}


def link(path):
    """Placeholder for a link, resolved relative to each output file when written."""
    return f"<<{os.path.abspath(path)}>>"


def resolve_links(text, base_dir):
    return re.sub(r"<<(.*?)>>", lambda m: os.path.relpath(m.group(1), base_dir), text)


def join(s):
    s = sorted(x for x in s if x and x != "None")
    return ", ".join(f"`{x}`" for x in s) if s else "–"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Generate a markdown report for a batch of runs.")
    ap.add_argument("--results", default="results/raw")
    ap.add_argument("--tag", required=True, help="run tag(s), comma-separated")
    ap.add_argument("--group-by", default="stack")
    ap.add_argument("--baseline")
    ap.add_argument("--out", help="output directory (default results/reports/<tag>)")
    ap.add_argument("--latest", help="also write a copy here, e.g. results/report.md")
    ap.add_argument("--title", help="report title")
    ap.add_argument("filters", nargs=argparse.REMAINDER,
                    help="extra compare_groups.py arguments after --, e.g. -- --stack ros2")
    args = ap.parse_args()

    out = args.out or os.path.join("results", "reports", args.tag.replace(",", "+"))
    os.makedirs(out, exist_ok=True)
    extra = [a for a in args.filters if a != "--"]

    cmd = [sys.executable, os.path.join(HERE, "compare_groups.py"), "--results", args.results,
           "--tag", args.tag, "--group-by", args.group_by,
           "--json", os.path.join(out, "report.json"), "--csv", os.path.join(out, "runs.csv"),
           "--markdown", os.path.join(out, "stats.md")] + extra
    if args.baseline:
        cmd += ["--baseline", args.baseline]
    cg = subprocess.run(cmd, capture_output=True, text=True)
    stats_ok = cg.returncode == 0 or os.path.exists(os.path.join(out, "report.json"))

    lines = [f"# {args.title or 'Mapping comparison report'}: `{args.tag}`", "",
             f"Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} by `metrics/make_report.py`. "
             f"Grouped by `{args.group_by}`. Metric definitions: [docs/metrics.md](https://github.com/ATemova/"
             "ros1-ros2-mapping-comparison/blob/main/docs/metrics.md).", ""]

    if not stats_ok:
        lines += ["## Statistics", "", "Statistics could not be computed:", "", "```",
                  (cg.stderr or cg.stdout).strip(), "```", ""]
        rows, groups, figs, fig_note = [], [], [], None
    else:
        rep = read_json(os.path.join(out, "report.json"))
        rows = read_runs_csv(os.path.join(out, "runs.csv"))
        groups = rep["groups"]
        prov = provenance(rows, groups)

        lines += ["## Setup", "",
                  "| Group | Runs | Image | Distro | RMW | slam_toolbox | Condition |",
                  "|---|---|---|---|---|---|---|"]
        for g in groups:
            pg = prov["per_group"].get(g, {})
            n = sum(1 for r in rows if r["group"] == g)
            lines.append(f"| **{g}** | {n} | {join(pg.get('images', []))} | {join(pg.get('distro', []))} | "
                         f"{join(pg.get('rmw', []))} | {join(pg.get('slam_toolbox', []))} | "
                         f"{join(pg.get('condition', []))} |")
        c = rep.get("condition", {})
        lines += ["", f"Bag `{c.get('bag_id')}` at {c.get('rate')}× · algorithm `{c.get('algo')}` · "
                      f"mode `{c.get('mode')}`.", ""]

        with open(os.path.join(out, "stats.md")) as f:
            stats_md = f.read()
        lines += ["## Results", "", stats_md.replace("## ", "### ", 1), ""]
        if cg.returncode != 0 and cg.stderr.strip():
            lines += ["> " + cg.stderr.strip().replace("\n", "\n> "), ""]

        figs, fig_note = figures(rows, groups, out)
        if figs or fig_note:
            lines += ["## Figures", ""]
            for name, caption in figs:
                lines += [f"![{caption}]({link(os.path.join(out, 'figures', name))})", "", f"*{caption}.*", ""]
            if fig_note:
                lines += [fig_note, ""]

        try:
            from map_quality import consistency, consistency_markdown
            mc = consistency(args.results, args.tag, 10.0, args.group_by if args.group_by != "condition" else "variant")
            if mc["order"]:
                md = consistency_markdown(mc)
                with open(os.path.join(out, "map_consistency.md"), "w") as f:
                    f.write(md)
                with open(os.path.join(out, "map_consistency.json"), "w") as f:
                    json.dump(mc, f, indent=2)
                lines += [md.replace("## ", "## ", 1), ""]
        except Exception as e:  # noqa: BLE001
            lines += ["## Map consistency", "", f"Not computed: {type(e).__name__}: {e}", ""]

        lines += ["## Provenance", "",
                  f"- Code: {join(prov['commits'])}" + (" (**uncommitted changes present**)" if prov["dirty"] else ""),
                  f"- Bag sha256: {join(prov['bags'])}",
                  f"- SLAM parameters sha256: {join(prov['configs'])}",
                  f"- Hosts: {join(prov['hosts'])}",
                  "- Per run: `run_meta.json` (conditions, status), `run_manifest.json` (image, versions, hashes), "
                  "`run_metrics.json` (all metrics), `effective_params.json` (parameters the node held).", "",
                  "## Runs", "", "| Group | Run | CPU mean (%) |", "|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['group']} | [{r.get('experiment_id') or os.path.basename(r['run_dir'])}]"
                         f"({link(r['run_dir'])}) | "
                         f"{fnum(r.get('cpu_mean')) or 0:.2f} |")
        lines.append("")

    report = "\n".join(lines)
    targets = [os.path.join(out, "report.md")] + ([args.latest] if args.latest else [])
    for target in targets:
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w") as f:
            f.write(resolve_links(report, os.path.dirname(os.path.abspath(target))))
        print(target)

    if not stats_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
