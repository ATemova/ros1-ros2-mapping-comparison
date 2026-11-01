#!/usr/bin/env python3
"""How many runs does each comparison need? Estimated from pilot runs.

    sample_size.py --tag pilot                         ROS1 vs ROS2
    sample_size.py --tag pilot --stack ros2 --group-by rmw
    sample_size.py --tag pilot --power 0.9 --planned-runs 8 --markdown sample_size.md

Selects and groups runs exactly like compare_groups.py (same filters, same pooling checks).
For every metric and every group against the baseline it reports, from the pilot runs:

    difference of means, pooled SD, effect size d = |difference| / pooled SD,
    runs per group needed to detect that difference (two-sided, alpha, power),
    the smallest difference detectable with --planned-runs runs per group.

Runs needed is computed for the two-sample t-test (exact noncentral-t power, matches
statsmodels) and then divided by 0.864, the lowest asymptotic relative efficiency of the
Mann-Whitney U test the reports use, so it holds for any distribution shape. It is never
below 4, the smallest group size at which a two-sided Mann-Whitney test can reach p < 0.05.
Pilot estimates of d are noisy: with 3 pilot runs per group treat the numbers as a rough
guide and prefer the larger of the plan and the metrics that matter most for the study.
Needs numpy.
"""

import argparse
import json
import math
import sys
from statistics import mean, stdev

from compare_groups import add_selection_args, available_metrics, fmt, label, load_groups
from stats_utils import min_detectable_d, runs_needed

MWU_ARE = 0.864
MWU_MIN_RUNS = 4
MAX_RUNS = 500


def plan(groups, order, alpha, power, planned):
    base = order[0]
    d_min = min_detectable_d(planned, power, alpha)
    rows = []
    for key, name, unit in available_metrics(groups):
        a = [r["metrics"][key] for r in groups[base]]
        for g in order[1:]:
            b = [r["metrics"][key] for r in groups[g]]
            row = {"metric": key, "label": name, "unit": unit, "group": g, "baseline": base,
                   "n_pilot": [len(a), len(b)], "diff": mean(b) - mean(a)}
            if len(a) < 2 or len(b) < 2:
                row["note"] = "needs at least 2 pilot runs per group"
                rows.append(row)
                continue
            sp = math.sqrt(((len(a) - 1) * stdev(a) ** 2 + (len(b) - 1) * stdev(b) ** 2) / (len(a) + len(b) - 2))
            row["pooled_sd"] = sp
            row["mde_planned"] = d_min * sp
            if sp == 0:
                row["d"] = math.inf if row["diff"] else 0.0
            else:
                row["d"] = abs(row["diff"]) / sp
            n_t = runs_needed(row["d"], power, alpha, MAX_RUNS)
            row["runs_t"] = n_t
            row["runs"] = None if n_t is None else max(MWU_MIN_RUNS, math.ceil(n_t / MWU_ARE))
            if row["d"] == 0:
                row["note"] = "no difference in the pilot"
            elif n_t is None:
                row["note"] = f"more than {MAX_RUNS} runs: difference too small to matter at this noise"
            rows.append(row)
    return {"alpha": alpha, "power": power, "planned_runs": planned, "d_detectable_planned": d_min,
            "baseline": base, "groups": order, "rows": rows}


def to_markdown(res, group_by):
    lines = [
        f"## Runs needed per group (power {res['power']:g}, two-sided α = {res['alpha']:g})",
        "",
        f"Pilot groups: " + ", ".join(label(g, group_by) for g in res["groups"])
        + f" · baseline **{label(res['baseline'], group_by)}** · with {res['planned_runs']} runs per group "
        f"the smallest detectable effect is d = {res['d_detectable_planned']:.2f}.",
        "",
        "| Metric | Comparison | Pilot n | Difference | Pooled SD | d | Runs needed | Detectable with "
        f"{res['planned_runs']} runs |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in res["rows"]:
        u = f" {r['unit']}" if r["unit"] else ""
        comp = f"{label(r['group'], group_by)} vs {label(r['baseline'], group_by)}"
        n = f"{r['n_pilot'][1]} / {r['n_pilot'][0]}"
        if "pooled_sd" not in r:
            lines.append(f"| {r['label']} | {comp} | {n} | {fmt(r['diff'])}{u} | n/a | n/a | {r['note']} | n/a |")
            continue
        d = "∞" if math.isinf(r["d"]) else f"{r['d']:.2f}"
        runs = str(r["runs"]) if r["runs"] is not None else f"> {MAX_RUNS}"
        if r.get("note") == "no difference in the pilot":
            runs = "–"
        lines.append(f"| {r['label']} | {comp} | {n} | {fmt(r['diff'])}{u} | {fmt(r['pooled_sd'])}{u} | {d} | "
                     f"{runs} | ≥ {fmt(r['mde_planned'])}{u} |")

    needed = [r["runs"] for r in res["rows"] if r.get("runs")]
    if needed:
        within = sum(1 for n in needed if n <= res["planned_runs"])
        lines += ["", f"{within} of {len(needed)} observed differences are detectable with "
                      f"{res['planned_runs']} runs per group; the median needs {sorted(needed)[len(needed) // 2]} runs."]
    lines += [
        "",
        "Runs needed: two-sample t-test (exact power) divided by 0.864 for the Mann-Whitney test, "
        f"minimum {MWU_MIN_RUNS}. Pilot effect sizes are noisy estimates; plan for the metrics the study "
        "is about, not for every row.",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Runs needed per comparison, from pilot runs.")
    add_selection_args(ap)
    ap.add_argument("--power", type=float, default=0.8)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--planned-runs", type=int, default=5, help="runs per group you plan (default 5)")
    ap.add_argument("--markdown", help="write the table to a file")
    ap.add_argument("--json", help="write the full result as JSON")
    args = ap.parse_args()

    groups, order, _ = load_groups(args)
    if len(order) < 2:
        print(f"Need at least two groups by '{args.group_by}' (found: {', '.join(order)}).", file=sys.stderr)
        sys.exit(1)
    res = plan(groups, order, args.alpha, args.power, args.planned_runs)
    md = to_markdown(res, args.group_by)
    print(md, end="")
    if args.markdown:
        with open(args.markdown, "w") as f:
            f.write(md)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(res, f, indent=2, default=lambda o: None)
            f.write("\n")


if __name__ == "__main__":
    main()
