<p align="center">
  <a href="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml">
    <img src="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <img src="https://img.shields.io/badge/ROS1-Noetic-blue?style=flat-square&logo=ros" />
  <img src="https://img.shields.io/badge/ROS2-Humble-blueviolet?style=flat-square&logo=ros" />
  <img src="https://img.shields.io/badge/Sensor-2D%20LiDAR-informational?style=flat-square" />
  <img src="https://img.shields.io/badge/Platform-Mobile%20Robot-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/Study-System--Level%20Comparison-success?style=flat-square" />
  <a href="https://github.com/ATemova/ros1-ros2-mapping-comparison/releases/tag/v0.1.0">
    <img src="https://img.shields.io/badge/Release-v0.1.0-blue?style=flat-square" alt="Release v0.1.0" />
  </a>
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

Experiments are conducted on a real mobile robot operating in a controlled indoor environment. All runs follow fixed trajectories and identical environmental conditions to ensure a fair and reproducible comparison.

## Repository structure

| Path | Purpose |
|---|---|
| `experiments/` | Run scripts (`run_ros1.sh`, `run_ros2.sh`) that orchestrate one timestamped experiment run, plus protocol notes. |
| `ros1/` | ROS1 Noetic GMapping launch file and parameters. |
| `ros2/` | ROS2 Humble `slam_toolbox` launch file and parameters. |
| `metrics/` | CPU/memory logger, summary and ROS1-vs-ROS2 comparison scripts (latency logger is a placeholder). |
| `plots/` | Scripts that render CPU, memory and occupancy-grid map plots as PNGs. |
| `results/raw/` | Per-run output (`cpu_mem.csv`, archived parameters), one folder per run ID. |
| `docker/` | Dockerfiles for ROS1 Noetic and ROS2 Humble environments. |
| `.github/workflows/` | CI: linting, analysis smoke test, ROS1/ROS2 container runs, Docker builds. |

## Requirements

| Component | Version |
|---|---|
| OS | Ubuntu 20.04 (ROS1 Noetic), Ubuntu 22.04 (ROS2 Humble), or Docker on any host |
| ROS1 | Noetic + `ros-noetic-slam-gmapping`, `ros-noetic-map-server` |
| ROS2 | Humble + `ros-humble-slam-toolbox` |
| Python | 3.8+ (3.8 on Noetic, 3.10 on Humble; CI uses 3.11) |
| Python packages | `psutil`, `pandas`, `matplotlib` (`pip install -r requirements.txt`) |
| Hardware | 2D LiDAR publishing on `/scan`, required only for live mapping runs |

On ROS images, install the Python packages with apt instead: `apt-get install -y python3-psutil python3-pandas python3-matplotlib`. `summarize_metrics.py` and `compare_runs.py` use only the standard library.

The pipeline, metrics and analysis can be exercised without hardware.

> ROS1 Noetic does not run natively on macOS, and ROS2 Humble is not officially supported there either. On a Mac, use the Docker workflow below (pipeline testing only — a container cannot access USB/serial LiDAR hardware).

## Quick Start (Docker)

Run each command from the repository root. Build the image once, then run.

ROS1:

```
docker build -f docker/Dockerfile.ros1 -t ros1-mapping .
docker run -it --rm -v "$PWD":/work -w /work ros1-mapping ./experiments/run_ros1.sh
```

ROS2:

```
docker build -f docker/Dockerfile.ros2 -t ros2-mapping .
docker run -it --rm -v "$PWD":/work -w /work ros2-mapping ./experiments/run_ros2.sh
```

The run scripts resolve their own location and `cd` to the repo root, so they work regardless of the calling directory — but the Docker `-v "$PWD":/work` mount must point at the repository root (the folder containing `experiments/`), not its parent.

Use a shorter duration while testing: `-e DURATION=20`.

## Running Experiments (native)

On a machine with ROS already installed:

```
source /opt/ros/noetic/setup.bash
./experiments/run_ros1.sh
```

```
source /opt/ros/humble/setup.bash
./experiments/run_ros2.sh
```

Each script:

- Resolves the repo root and creates a timestamped output directory under `results/raw/`
- Sources ROS if it is not already sourced (`ROS_DISTRO` overridable)
- Launches the mapping pipeline by file path (no catkin/ament package build required) and checks that it started
- Logs system-wide CPU and memory usage (`psutil`) to `cpu_mem.csv`
- Archives the mapping parameters used for the run

Run duration defaults to 300 s and is overridable: `DURATION=60 ./experiments/run_ros1.sh`.

> The ROS1 launch file (`ros1/launch/mapping.launch`) currently starts the GMapping SLAM node and expects LiDAR scan data on `/scan`. A LiDAR driver and sensor hardware are required for live mapping.

## Analysis

Summarize a run (standard library only — runs in any ROS image):

```
python3 metrics/summarize_metrics.py results/raw/ros1/<run_id>/cpu_mem.csv
```

Compare a ROS1 run against a ROS2 run:

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

Each experiment run generates a unique identifier, archives mapping parameters, logs system metrics, and stores results in a structured, timestamped directory.

## Limitations

This study focuses on system-level behavior and qualitative mapping outcomes. It does not attempt to benchmark SLAM accuracy quantitatively, provide statistical guarantees across diverse environments, or evaluate large-scale deployment scenarios. These aspects are considered future work.

Known limitations of the current pipeline (v0.1.0):

- The CPU/memory logger records system-wide usage, not per-process usage of the SLAM node.
- The ROS1 launch file does not yet load `ros1/params/mapping.yaml`; GMapping runs with its default parameters, so ROS1 and ROS2 configurations are not yet aligned.
- Maps are not yet saved automatically at the end of a run.
- Message latency logging (`metrics/ros_latency_logger.py`) is a placeholder.
- `results/raw/` contains only short pipeline test runs, not experimental data.

## Status

**v0.1.0 – early release, experiments in progress.** The experiment pipeline and repository structure are in place. Experimental runs on the real robot, results, figures and analysis will be added in later releases. See [CHANGELOG.md](CHANGELOG.md).

## License

See [LICENSE](LICENSE).
