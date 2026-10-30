# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Experimental design: same algorithm and parameters on both stacks, identical recorded input, repeated runs with statistics.

### Added

- Shared `config/slam_toolbox.yaml` loaded unchanged by both stacks: ROS1 via `rosparam load`, ROS2 as a parameter dict.
- `slam_toolbox` (synchronous) on ROS1 Noetic, selected with `ALGO=slam_toolbox` (new default); GMapping kept as a ROS1-only baseline with real GMapping parameters in `config/gmapping.yaml`.
- Bag replay mode: `BAG=<bag>` replays recorded input with `--clock` / `use_sim_time`; ROS2 playback uses `config/qos_overrides.yaml`.
- Bag tools: `experiments/record_bag.sh`, `experiments/convert_bag.sh` (ROS1 ⇄ ROS2 via `rosbags`, Humble-compatible output), `experiments/inspect_bag.py` (rejects bags recorded while SLAM was running), `experiments/make_synthetic_bag.py` (deterministic test bag).
- `experiments/run_matrix.sh`: repeated, counterbalanced ROS1/ROS2 replay runs in fresh containers, optional resource pinning, batch report in `results/reports/<tag>/`.
- `run_meta.json` per run (stack, algorithm, mode, bag, rate, tag, map received, exit status, git commit, host).
- `metrics/compare_groups.py` and `metrics/stats_utils.py`: mean ± 95% CI, Mann-Whitney U (exact / normal with tie correction), Cliff's delta; refuses to mix conditions.
- Unit tests for the statistics (`tests/test_stats.py`), checked against scipy.
- CI: synthetic bag job, ROS1/ROS2 replay runs that must produce a map, cross-stack comparison in the job summary, unit tests, bag tooling check in the ROS2 image.

### Changed

- `run_ros1.sh` / `run_ros2.sh` share `experiments/common.sh`. Launched processes run in their own process groups and are stopped together (SIGINT, then SIGTERM, then SIGKILL), so no node outlives a run.
- Runs fail when the SLAM package is missing or the SLAM node does not come up, instead of continuing without SLAM.
- ROS2 image ships `rosbags`; ROS1 image ships `ros-noetic-slam-toolbox`.

### Removed

- `ros1/params/mapping.yaml` and `ros2/params/mapping.yaml` (replaced by `config/`). The ROS1 file was never loaded and used non-GMapping parameter names.

## [0.1.0] - 2026-10-16

First public release of the experimental framework. Experiments and analysis are still in progress; this release contains no final results.

### Added

- ROS1 Noetic mapping pipeline: GMapping launch file (`ros1/launch/mapping.launch`) subscribing to `/scan`, and a parameter file (`ros1/params/mapping.yaml`).
- ROS2 Humble mapping pipeline: `slam_toolbox` (synchronous) launch file (`ros2/launch/mapping.launch.py`) with parameter file (`ros2/params/mapping.yaml`). Falls back to a log message when `slam_toolbox` is not installed so the pipeline can be smoke-tested.
- Experiment runners `experiments/run_ros1.sh` and `experiments/run_ros2.sh`: timestamped output directories under `results/raw/`, automatic ROS sourcing, launch by file path (no catkin/colcon build needed), startup validation of the mapping process, parameter archiving, configurable `DURATION`, and process cleanup on exit.
- Experiment protocol notes (`experiments/notes.md`).
- System-wide CPU and memory logger (`metrics/cpu_memory_logger.py`) writing `cpu_mem.csv`.
- Metric summary (`metrics/summarize_metrics.py`) and ROS1-vs-ROS2 run comparison (`metrics/compare_runs.py`) reporting average, median, minimum and maximum CPU and memory, with validation for missing, empty or malformed CSV files.
- Plotting scripts for CPU (`plots/plot_cpu.py`), memory (`plots/plot_memory.py`) and occupancy-grid maps (`plots/plot_maps.py`).
- Dockerfiles for ROS1 Noetic and ROS2 Humble environments.
- GitHub Actions CI: shell/Python/YAML linting, analysis pipeline smoke test, ROS1 and ROS2 container smoke runs, Docker image builds.
- Root `requirements.txt` pointing to `metrics/requirements.txt`.
- `CHANGELOG.md`.

### Changed

- `.gitignore` extended for Python, ROS1 (catkin), ROS2 (colcon), ROS bags (`*.bag`, `*.db3`, `*.mcap`) and large generated result files.
- README: version/status badge, "Requirements" and "Repository structure" sections, known limitations; the "Recent Improvements" list moved into this changelog.
- `metrics/compare_runs.py` marked executable.

