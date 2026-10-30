<p align="center">
  <a href="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml"><img src="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/ROS1-Noetic-blue?style=flat-square&logo=ros" alt="ROS1 Noetic" />
  <img src="https://img.shields.io/badge/ROS2-Humble-blueviolet?style=flat-square&logo=ros" alt="ROS2 Humble" />
  <img src="https://img.shields.io/badge/Sensor-2D%20LiDAR-informational?style=flat-square" alt="2D LiDAR" />
  <img src="https://img.shields.io/badge/Platform-Mobile%20Robot-orange?style=flat-square" alt="Mobile Robot" />
  <img src="https://img.shields.io/badge/Study-System--Level%20Comparison-success?style=flat-square" alt="System-Level Comparison" />
  <a href="https://github.com/ATemova/ros1-ros2-mapping-comparison/releases/tag/v0.1.0"><img src="https://img.shields.io/badge/Release-v0.1.0-blue?style=flat-square" alt="Release v0.1.0" /></a>
  <img src="https://img.shields.io/badge/Status-v0.1.0%20early%20release%20%E2%80%93%20experiments%20in%20progress-yellow?style=flat-square" alt="Status: v0.1.0 – early release, experiments in progress" />
</p>

# ROS1 vs ROS2 Mapping Comparison

This repository contains experimental scripts, configuration files, and analysis tools used in the study:

**"A Practical Comparison of ROS1 and ROS2 Mapping Pipelines on a Real Mobile Robot"**

The objective of this work is to empirically evaluate the differences between ROS1 and ROS2 mapping pipelines under controlled, repeatable real-world conditions.


## Overview

The Robot Operating System (ROS) is widely adopted in mobile robotics. While ROS1 has been the dominant middleware for many years, ROS2 introduces architectural changes aimed at improving performance, reliability, and scalability.
As robotics systems transition from ROS1 to ROS2, it becomes essential to understand how these architectural differences affect practical deployment scenarios such as real-time mapping.
This project provides a system-level comparison of ROS1 and ROS2 mapping pipelines using identical hardware, sensor configurations, and experimental conditions on a real mobile robot.

> **Status: v0.1.0 – early release, experiments in progress.**
> This release provides the experiment pipeline, configuration and analysis tooling. It contains no final results or findings. See [CHANGELOG.md](CHANGELOG.md).

## Experimental Scope

The comparison focuses on:

- System-level performance (CPU and memory utilization)
- Runtime stability during mapping execution
- Qualitative consistency of generated maps

Sensor data is recorded once on a real mobile robot in a controlled indoor environment, then replayed to both stacks. Both stacks run the same SLAM algorithm (`slam_toolbox`, synchronous mode) with one shared parameter file, so differences can be attributed to the middleware rather than to the algorithm, the parameters or the trajectory. Every condition is repeated and compared statistically. See [experiments/notes.md](experiments/notes.md) for the full protocol.

## Repository structure

| Path | Purpose |
|---|---|
| `config/` | Shared SLAM parameters (`slam_toolbox.yaml`, loaded unchanged by both stacks), ROS1-only `gmapping.yaml`, ROS2 replay QoS overrides. |
| `experiments/` | Run scripts (`run_ros1.sh`, `run_ros2.sh`, shared `common.sh`), batch runner `run_matrix.sh`, bag tools (`record_bag.sh`, `convert_bag.sh`, `inspect_bag.py`, `make_synthetic_bag.py`), protocol notes. |
| `ros1/` | ROS1 Noetic launch file (`slam_toolbox` or GMapping). |
| `ros2/` | ROS2 Humble launch file (`slam_toolbox`). |
| `data/bags/` | Recorded bags for replay (git-ignored). |
| `metrics/` | CPU/memory logger, single-run summary, two-run comparison, repeated-run statistics (latency logger is a placeholder). |
| `tests/` | Unit tests for the statistics helpers. |
| `plots/` | Scripts that render CPU, memory and occupancy-grid map plots as PNGs. |
| `results/raw/` | Per-run output (`cpu_mem.csv`, `run_meta.json`, archived parameters), one folder per run ID. |
| `results/reports/` | Batch reports written by `run_matrix.sh`. |
| `docker/` | Dockerfiles for ROS1 Noetic and ROS2 Humble environments. |
| `.github/workflows/` | CI: linting, analysis smoke test, ROS1/ROS2 container runs, Docker builds. |

## Requirements

| Component | Version |
|---|---|
| OS | Ubuntu 20.04 (ROS1 Noetic), Ubuntu 22.04 (ROS2 Humble), or Docker on any host |
| ROS1 | Noetic + `ros-noetic-slam-toolbox`, `ros-noetic-slam-gmapping`, `ros-noetic-map-server` |
| ROS2 | Humble + `ros-humble-slam-toolbox` |
| Python | 3.8+ (3.8 on Noetic, 3.10 on Humble; CI uses 3.11) |
| Python packages | `psutil`, `pandas`, `matplotlib` (`pip install -r requirements.txt`); bag tools: `rosbags` (`pip install -r experiments/requirements-bags.txt`, Python ≥ 3.10, included in the ROS2 image) |
| Hardware | 2D LiDAR publishing on `/scan`, required only for recording bags and live runs |

On ROS images, install the Python packages with apt instead: `apt-get install -y python3-psutil python3-pandas python3-matplotlib`. `summarize_metrics.py` and `compare_runs.py` use only the standard library.

The pipeline, metrics and analysis can be exercised without hardware.

> ROS1 Noetic does not run natively on macOS, and ROS2 Humble is not officially supported there either. On a Mac, use the Docker workflow below (pipeline testing only — a container cannot access USB/serial LiDAR hardware).

## Quick Start (Docker)

Build both images once from the repository root:

```
docker build -f docker/Dockerfile.ros1 -t ros1-mapping .
docker build -f docker/Dockerfile.ros2 -t ros2-mapping .
```

Try the full replay pipeline without a robot, using a synthetic bag:

```
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/work -w /work ros2-mapping python3 experiments/make_synthetic_bag.py
BAG=data/bags/synthetic.bag RUNS=3 ./experiments/run_matrix.sh
```

> A container cannot access USB/serial LiDAR hardware, so on a Mac use Docker for replay only.

## Running Experiments

### 1. Record a bag on the robot

With the base and LiDAR drivers running and **no SLAM node**:

```
source /opt/ros/noetic/setup.bash
DURATION=300 ./experiments/record_bag.sh corridor_01
```

This writes `data/bags/corridor_01.bag` (or `data/bags/corridor_01/` on ROS2) with `/scan /odom /tf /tf_static`, and validates it when `rosbags` is installed.

### 2. Repeated replay runs (main comparison)

```
BAG=data/bags/corridor_01.bag RUNS=5 ./experiments/run_matrix.sh
```

`run_matrix.sh`:

- Converts the bag to the other ROS format if needed and validates it
- Runs `RUNS` rounds per stack in fresh containers, alternating the order (ROS1→ROS2, ROS2→ROS1, ...)
- Tags every run with `RUN_TAG` and writes `results/reports/<RUN_TAG>/report.md`, `report.json`, `runs.csv`

Options: `ALGO`, `RATE`, `SETTLE`, `RUN_TAG`, `COOLDOWN`, `BUILD=1`, and `DOCKER_ARGS` for resource pinning (e.g. `DOCKER_ARGS="--cpuset-cpus=2,3 --memory=4g"`).

### Single runs

```
BAG=data/bags/corridor_01.bag ./experiments/run_ros1.sh
BAG=data/bags/corridor_01 ./experiments/run_ros2.sh
```

Without `BAG`, the scripts run live against `/scan` for `DURATION` seconds (default 300). Each run:

- Creates `results/raw/<ros1|ros2>/<run_id>/`
- Starts SLAM (`ALGO=slam_toolbox` by default; `ALGO=gmapping` is available on ROS1 as a baseline) and waits until the node is up
- Replays the bag with `--clock` and `use_sim_time` (ROS2 uses `config/qos_overrides.yaml`), or runs for `DURATION` live
- Logs system-wide CPU and memory to `cpu_mem.csv`
- Checks that a `/map` was published (required in replay mode)
- Archives the parameter file and writes `run_meta.json` (stack, algorithm, mode, bag, rate, tag, git commit, host)
- Stops every launched process group on exit

`BAG` accepts either form (`x.bag` or `x/`); the scripts pick the one matching their stack. Convert manually with `./experiments/convert_bag.sh data/bags/x.bag`.

## Analysis

Summarize a run (standard library only — runs in any ROS image):

```
python3 metrics/summarize_metrics.py results/raw/ros1/<run_id>/cpu_mem.csv
```

Statistics across repeated runs (mean ± 95% CI, Mann-Whitney U, Cliff's delta):

```
python3 metrics/compare_groups.py --tag <run_tag>
python3 metrics/compare_groups.py --algo slam_toolbox --mode replay --bag corridor_01 --json report.json
```

Compare a single ROS1 run against a single ROS2 run:

```
python3 metrics/compare_runs.py results/raw/ros1/<run_id>/cpu_mem.csv results/raw/ros2/<run_id>/cpu_mem.csv
```

Plot CPU / memory (needs `pandas` + `matplotlib`; pass a CSV path, or `--ros ros1|ros2` for the latest run):

```
python3 plots/plot_cpu.py --ros ros1
python3 plots/plot_memory.py --ros ros2
python3 plots/plot_maps.py path/to/map.pgm
```

Plots are written as PNGs next to the source CSV.

## Reproducibility

This repository provides configuration files and experiment scripts to support reproducibility on similar mobile robot platforms equipped with a 2D LiDAR sensor. No proprietary firmware or internal company code is included.

Each experiment run generates a unique identifier, archives mapping parameters, logs system metrics, records its conditions in `run_meta.json`, and stores results in a structured, timestamped directory. Replay runs use recorded sensor data, so a batch can be re-run on another machine from the same bag.

## Limitations

This study focuses on system-level behavior and qualitative mapping outcomes. It does not attempt to benchmark SLAM accuracy quantitatively, provide statistical guarantees across diverse environments, or evaluate large-scale deployment scenarios. These aspects are considered future work.

Known limitations of the current pipeline:

- The CPU/memory logger records system-wide usage (including the bag player), not per-process usage of the SLAM node.
- Maps are not yet saved automatically at the end of a run.
- GMapping is ROS1-only; the comparison across stacks uses `slam_toolbox`.
- Message latency logging (`metrics/ros_latency_logger.py`) is a placeholder.
- `results/raw/` contains only short pipeline test runs, not experimental data.

## Status

**v0.1.0 – early release, experiments in progress.** The experiment pipeline and repository structure are in place. Experimental runs on the real robot, results, figures and analysis will be added in later releases. See [CHANGELOG.md](CHANGELOG.md).

## License

See [LICENSE](LICENSE).
