# Metrics

Definitions of every metric: [docs/metrics.md](../docs/metrics.md).

| Script | Purpose |
|---|---|
| `cpu_memory_logger.py` | System-wide CPU/memory (`cpu_mem.csv`), per-role process CPU/RSS (`proc_metrics.csv`), network counters (`net_io.csv`). Needs `psutil`. |
| `ros_latency_logger.py` | Records scan, map and TF events (`latency_events.csv`) on ROS1 or ROS2. |
| `latency_analysis.py` | Latency, rates, jitter and drops from `latency_events.csv`. |
| `trajectory.py` | Trajectory export (TUM) and ATE/RPE (evo semantics). |
| `map_quality.py` | Map accuracy vs. a reference, and cross-run map consistency. |
| `analyze_run.py` | Runs all of the above on one run directory → `run_metrics.json`. |
| `compare_groups.py` | Statistics across repeated runs, grouped by stack, RMW, distro, variant or condition: mean ± 95% CI, Mann-Whitney U, Cliff's delta, Kruskal-Wallis + Holm for 3+ groups, parameter identity. |
| `make_report.py` | Markdown report with tables, figures, map consistency and provenance (`make report`). |
| `summarize_metrics.py`, `compare_runs.py` | Quick summaries of one run / one run per stack (system-wide CPU/memory). |
| `stats_utils.py`, `metrics_utils.py` | Helpers. |

`compare_groups.py`, `summarize_metrics.py` and `compare_runs.py` need only the standard
library. The analysis scripts need `numpy` (and `pyyaml` for some map files), which the ROS
images provide.
