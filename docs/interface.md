# Stable interface

From v1.0.0 the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) for
the surface listed here. Anything here can only change incompatibly in a major release.
Everything that is not listed is internal or experimental and can change in any release.

`docs/interface.json` records this surface. `make interface` (also part of `make check` and CI)
compares it with the current tree. The check fails on a breaking change and lists additions,
which you record with `make interface UPDATE=1` in the same pull request.

## What counts as breaking

| Breaking (major release) | Compatible (minor or patch) |
|---|---|
| Removing or renaming a make target, a make variable, a documented environment variable, a CLI option, a positional argument or a subcommand | Adding any of these |
| Changing the meaning or default of a stable option in a way that changes results | Adding an option whose default keeps the old behaviour |
| Removing a schema property, changing its type, making a field required, changing `schema_version` | Adding an optional property or a `summary` metric ([data-format.md](data-format.md)) |
| Moving or renaming files in the run-folder layout below | Adding files to a run folder or report folder |
| Changing a metric's definition in [metrics.md](metrics.md) under the same key | Adding a metric under a new key |

## Deprecation

You can't remove a stable name in a minor release. Deprecate it instead:

1. Keep the old name working and print a warning on stderr that names the replacement.
2. Mark it *deprecated* here and in the CHANGELOG (`### Deprecated`).
3. Remove it in the next major release at the earliest, never sooner than one minor release after the deprecation.

## Data formats

- Run folder: `results/raw/<run_tag>/<run_id>/`, with `run_id` = `<timestamp>_<variant>_<arch>`.
- Per-run files: `run_meta.json`, `run_metrics.json`, `run_manifest.json`, `effective_params.json`. Their schemas are in `schemas/`, at `schema_version` 1, with the versioning policy in [data-format.md](data-format.md). Per-run CSV logs (`cpu_mem.csv`, latency events) keep their column names.
- Report folder: `results/reports/<tag>/` with `report.md`, `stats.md`, `report.json` and `runs.csv`. The keys of `report.json` (`group_by`, `groups`, `baseline`, `condition`, `runs`, `metrics[].{metric,label,unit,groups,comparisons}`) are stable.
- Metric keys and definitions: [metrics.md](metrics.md).

## Makefile

Targets: `help`, `images`, `image-ros1`, `image-ros2`, `lock`, `pull`, `synthetic`, `experiment`,
`matrix`, `rmw`, `distros`, `stress`, `long`, `report`, `sample-size`, `paper-figures`,
`validate`, `test`, `lint`, `interface`, `check`, `sample-bag`, `dataset`.

Variables: `STACK`, `DISTRO`, `RMW`, `ALGO`, `RUNS`, `RATE`, `BAG`, `TAG`, `TAGS`, `GROUP_BY`,
`BASELINE`, `POWER`, `CPUS`, `CPU_SET`, `MEMORY`, `CONDITION`, `SETTLE`, `COOLDOWN`, `BUILD`,
`DOCKER_ARGS`, `VARIANTS`, `VERSION`, `IMAGE_REPO`, `METRICS`, `NAME`, `BAGS`, `SECONDS`,
`PYTHON`, `UPDATE`. `make help` describes them.

## Environment variables

- `experiments/run_ros1.sh` and `experiments/run_ros2.sh` (documented in the header of `experiments/common.sh`): `ALGO`, `BAG`, `RATE`, `SETTLE`, `STARTUP_WAIT`, `REQUIRE_MAP`, `REQUIRE_PARAMS`, `RUN_TAG`, `ROS_DISTRO`, `LOG_LATENCY`, `REFERENCE_TRAJ`, `REFERENCE_MAP`, `RMW`, `CPU_SET`, `CONDITION`. `DURATION`, `ROLE` and `CLOCK_WAIT` are recorded too, but they belong to experimental modes (below).
- `experiments/run_matrix.sh`: `VARIANTS`, `RUNS`, `ALGO`, `RATE`, `SETTLE`, `RUN_TAG`, `CPUS`, `CPU_SET`, `MEMORY`, `CONDITION`, `GROUP_BY`, `BASELINE`, `DOCKER_ARGS`, `BUILD`, `COOLDOWN`.

`IMAGE_ID`, `IMAGE_TAG` and `GIT_DIRTY` are set by the tooling and are not part of the interface.

## Command-line tools

The options, positional arguments and subcommands of these scripts are stable; `--help` describes them:

| Script | Covered |
|---|---|
| `metrics/compare_groups.py` | all options |
| `metrics/make_report.py` | all options |
| `metrics/analyze_run.py` | all options |
| `metrics/sample_size.py` | all options |
| `metrics/map_quality.py` | `compare`, `consistency` |
| `metrics/trajectory.py` | `extract`, `error` |
| `experiments/validate_runs.py` | all options |
| `experiments/cut_bag.py` | all options |
| `experiments/make_synthetic_bag.py` | all options |

Their stdout and markdown output are for people and may change; scripts that consume results
should read the JSON outputs.

## Experimental

These are usable but not covered yet, and may change in a minor release:

- `experiments/floorplan_to_map.py` and `metrics/map_quality.py register` (floor-plan references, #13). They are promoted once they've been used on the recorded bags.
- `metrics/paper_figures.py` (publication figures and tables, #22). The figure layout and table columns may still change for the paper. `make paper-figures` and its `TAGS`/`METRICS` variables are stable.
- Two-machine runs (`ROLE=slam`/`ROLE=player`, `CLOCK_WAIT`) and live mode (no `BAG`, `DURATION`).
- `ALGO=gmapping` (ROS1-only baseline).

## Internal

Not part of the interface: `experiments/common.sh` functions, `write_meta.py`, `write_manifest.py`,
`dump_params.py`, `check_params.py`, `bag_info.py`, `inspect_bag.py`, `convert_bag.sh`,
`record_bag.sh`, `fetch_sample_bag.sh`, `package_dataset.sh`, `check_interface.py`; the
loggers `metrics/cpu_memory_logger.py` and `metrics/ros_latency_logger.py`; the modules
`metrics/stats_utils.py`, `metrics/metrics_utils.py` and `metrics/latency_analysis.py`;
`plots/`; Docker build scripts and image internals (the published image names are
covered by [reproducibility.md](reproducibility.md)).

*Deprecated:* `metrics/summarize_metrics.py` and `metrics/compare_runs.py` (single-CSV tools
from v0.1). Use `analyze_run.py` and `compare_groups.py` instead. They'll be removed in v2.0.0.
