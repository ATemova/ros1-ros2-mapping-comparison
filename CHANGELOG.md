# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

