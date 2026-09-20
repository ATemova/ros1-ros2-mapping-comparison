<p align="center">
  <a href="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml">
    <img src="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <img src="https://img.shields.io/badge/ROS1-Noetic-blue?style=flat-square&logo=ros" />
  <img src="https://img.shields.io/badge/ROS2-Humble-blueviolet?style=flat-square&logo=ros" />
  <img src="https://img.shields.io/badge/Sensor-2D%20LiDAR-informational?style=flat-square" />
  <img src="https://img.shields.io/badge/Platform-Mobile%20Robot-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/Study-System--Level%20Comparison-success?style=flat-square" />
  <img src="https://img.shields.io/badge/Status-Active%20Development-yellow?style=flat-square" />
</p>

# ROS1 vs ROS2 Mapping Comparison

This repository contains experimental scripts, configuration files, and analysis tools used in the study:

**"A Practical Comparison of ROS1 and ROS2 Mapping Pipelines on a Real Mobile Robot"**

The objective of this work is to empirically evaluate the differences between ROS1 and ROS2 mapping pipelines under controlled, repeatable real-world conditions.


## Overview

The Robot Operating System (ROS) is widely adopted in mobile robotics. While ROS1 has been the dominant middleware for many years, ROS2 introduces architectural changes aimed at improving performance, reliability, and scalability.
As robotics systems transition from ROS1 to ROS2, it becomes essential to understand how these architectural differences affect practical deployment scenarios such as real-time mapping.
This project provides a system-level comparison of ROS1 and ROS2 mapping pipelines using identical hardware, sensor configurations, and experimental conditions on a real mobile robot.

## Recent Improvements

Recent development has focused on improving experiment validation, metric analysis, and ROS1/ROS2 CI testing:

- Improved metric summary statistics and analysis output.
- Added ROS1 and ROS2 metric comparison support.
- Improved metric input validation and error handling for missing, malformed, or invalid CSV files.
- Improved experiment launch error handling for missing or failed launch files.
- Added startup validation for ROS1 and ROS2 mapping processes.
- Added ROS2 `slam_toolbox` dependencies for CI testing.
- Added a ROS1 GMapping mapping node for CI testing.
- Added temporary metric test files to `.gitignore`.

## Experimental Scope

The comparison focuses on:

- System-level performance (CPU and memory utilization)
- Runtime stability during mapping execution
- Qualitative consistency of generated maps

Experiments are conducted on a real mobile robot operating in a controlled indoor environment. All runs follow fixed trajectories and identical environmental conditions to ensure a fair and reproducible comparison.

## Repository Layout

```
experiments/   run_ros1.sh, run_ros2.sh  -> orchestrate a single experiment run
ros1/          launch/ + params/         -> ROS1 GMapping launch and parameters
ros2/          launch/ + params/         -> ROS2 slam_toolbox launch and parameters
metrics/       logger + summary + comparison utilities
plots/         plot_cpu.py, plot_memory.py, plot_maps.py
results/raw/   per-run output (cpu_mem.csv, archived params)
docker/        Dockerfile.ros1, Dockerfile.ros2
```

## Prerequisites

- **ROS1 runs:** ROS1 Noetic (Ubuntu 20.04) — natively on the robot, or via the `ros:noetic` container.
- **ROS2 runs:** ROS2 Humble (Ubuntu 22.04) — natively on the robot, or via the `ros:humble` container.
- Python packages: see `metrics/requirements.txt` (`psutil`, `pandas`, `matplotlib`). On ROS images install them with apt: `apt-get install -y python3-psutil python3-pandas python3-matplotlib`. `summarize_metrics.py` uses only the standard library and needs none of them.
- A 2D LiDAR is required only for **live mapping runs**. The pipeline and metrics/analysis can be exercised without hardware.

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
- Logs CPU and memory usage using `psutil`
- Launches the mapping pipeline by file path (no catkin/ament package build required)
- Logs CPU and memory to `cpu_mem.csv`
- Archives the mapping parameters used for the run

Run duration defaults to 300 s and is overridable: `DURATION=60 ./experiments/run_ros1.sh`.

> The ROS1 launch file (`ros1/launch/mapping.launch`) currently starts the GMapping SLAM node and expects LiDAR scan data on `/scan`. A LiDAR driver and sensor hardware are required for live mapping.

## Analysis

Summarize a run (standard library only — runs in any ROS image):

```
python3 metrics/summarize_metrics.py results/raw/ros1/<run_id>/cpu_mem.csv
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

## Status

This project is under active development. Results, figures, and detailed analysis will be added as experiments are completed and evaluated.
