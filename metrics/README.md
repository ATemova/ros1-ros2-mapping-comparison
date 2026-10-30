# Metrics

| Script | Purpose |
|---|---|
| `cpu_memory_logger.py` | Logs system-wide CPU and memory to `cpu_mem.csv` during a run (needs `psutil`). |
| `summarize_metrics.py` | Average / median / min / max of one run. |
| `compare_runs.py` | Side-by-side summary of one ROS1 run and one ROS2 run. |
| `compare_groups.py` | Statistics across repeated runs: mean ± 95% CI, Mann-Whitney U, Cliff's delta. Groups runs by `run_meta.json` and checks that effective parameters are identical across runs. |
| `stats_utils.py` | Statistics helpers (standard library only, validated against scipy in `tests/`). |
| `ros_latency_logger.py` | Message latency (placeholder, future work). |

`summarize_metrics.py`, `compare_runs.py` and `compare_groups.py` use only the standard
library, so they run inside the ROS images.
