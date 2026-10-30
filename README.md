<p align="center">
  <a href="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml"><img src="https://github.com/ATemova/ros1-ros2-mapping-comparison/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/ROS1-Noetic-blue?style=flat-square&logo=ros" alt="ROS1 Noetic" />
  <img src="https://img.shields.io/badge/ROS2-Humble%20%7C%20Jazzy-blueviolet?style=flat-square&logo=ros" alt="ROS2 Humble | Jazzy" />
  <img src="https://img.shields.io/badge/RMW-Fast%20DDS%20%7C%20Cyclone%20DDS%20%7C%20Zenoh-informational?style=flat-square" alt="RMW: Fast DDS | Cyclone DDS | Zenoh" />
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

The question is timely: ROS1 Noetic reached end of life in May 2025, ROS2 Humble is supported until May 2027 and ROS2 Jazzy until May 2029, so teams still on ROS1 are migrating now, and teams on Humble will move to Jazzy next. Within ROS2, the middleware (RMW) is a deployment choice of its own: Fast DDS (default), Cyclone DDS, or Zenoh. The study therefore compares ROS1 with ROS2, the two ROS2 LTS releases with each other, and the RMWs within ROS2, under normal and constrained (embedded-like) conditions.

> **Status: v0.1.0 released; v0.2.0 in development – experiments in progress.**
> The repository provides the experiment pipeline, configuration and analysis tooling. It contains no final results or findings yet. See [CHANGELOG.md](CHANGELOG.md) (the *Unreleased* section lists everything since v0.1.0).

## Experimental Scope

The comparison focuses on:

- Resource use: system-wide and per process (SLAM node, middleware, launch, bag player), network traffic
- Timing: scan→map and scan→pose-correction latency, map update rate and jitter, time to first map, scan drops
- Mapping quality: trajectory error (ATE/RPE) and map accuracy against a reference, map consistency across runs
- Runtime stability during mapping execution

Every metric is defined in [docs/metrics.md](docs/metrics.md).

Comparisons: ROS1 vs ROS2, ROS2 Humble vs Jazzy, and Fast DDS vs Cyclone DDS vs Zenoh, each also under stress conditions (CPU cores or quota, memory limit, higher scan rates, 30+ minute runs).

Sensor data is recorded once on a real mobile robot in a controlled indoor environment, then replayed to every variant. Both stacks run the same SLAM algorithm (`slam_toolbox`, synchronous mode) with one shared parameter file, so differences can be attributed to the middleware rather than to the algorithm, the parameters or the trajectory. Every condition is repeated and compared statistically. See [experiments/notes.md](experiments/notes.md) for the full protocol.

## Repository structure

| Path | Purpose |
|---|---|
| `config/` | Shared SLAM parameters (`slam_toolbox.yaml`, loaded unchanged by both stacks), ROS1-only `gmapping.yaml`, ROS2 replay QoS overrides. |
| `Makefile` | One-command entry points (`make help`). |
| `docs/` | [Metric definitions](docs/metrics.md), [parameter mapping](docs/parameter_mapping.md) (generated, checked in CI), [dataset and DOI guide](docs/dataset.md). |
| `experiments/` | Run scripts (`run_ros1.sh`, `run_ros2.sh`, shared `common.sh`), batch runner `run_matrix.sh`, bag tools (`record_bag.sh`, `convert_bag.sh`, `inspect_bag.py`, `make_synthetic_bag.py`, `cut_bag.py`, `fetch_sample_bag.sh`), dataset packaging, run manifest, protocol notes. |
| `ros1/` | ROS1 Noetic launch file (`slam_toolbox` or GMapping). |
| `ros2/` | ROS2 launch file (`slam_toolbox`; plain node on Humble, lifecycle node from Jazzy on). |
| `data/bags/` | Recorded bags for replay (git-ignored). |
| `metrics/` | Loggers (resources, ROS timing events), per-run analysis (latency, trajectory ATE/RPE, map quality), repeated-run statistics. |
| `tests/` | Unit tests (statistics, map quality, trajectory, latency, run analysis). |
| `plots/` | Scripts that render CPU, memory and occupancy-grid map plots as PNGs. |
| `results/raw/` | Per-run output (raw logs, `run_meta.json`, `run_metrics.json`, saved map, trajectory, effective parameters), one folder per run ID. |
| `results/reports/`, `results/report.md` | Batch reports with tables and figures (`make report`); `results/report.md` is the latest. |
| `docker/` | Dockerfiles for ROS1 Noetic and ROS2 (Humble or Jazzy via build arg; Fast DDS, Cyclone DDS, Zenoh). |
| `.github/workflows/` | CI: lint and unit tests, ROS1 and ROS2 (Humble/Jazzy × Fast DDS/Cyclone DDS/Zenoh) replay runs on a synthetic bag with ground truth, comparison report, Docker end-to-end via `make`, sample bag when configured. |
| `CITATION.cff`, `.zenodo.json` | Citation metadata and Zenodo archiving. |

## Requirements

| Component | Version |
|---|---|
| OS | Docker on any host (recommended), or Ubuntu 20.04 (Noetic), 22.04 (Humble), 24.04 (Jazzy) |
| ROS1 | Noetic + `ros-noetic-slam-toolbox`, `ros-noetic-slam-gmapping`, `ros-noetic-map-server` |
| ROS2 | Humble or Jazzy + `slam-toolbox`, `nav2-map-server`, `rmw-cyclonedds-cpp`, `rmw-zenoh-cpp` (`ros-<distro>-...`) |
| Python | 3.8+ (3.8 on Noetic, 3.10 on Humble, 3.12 on Jazzy; CI uses 3.11) |
| Python packages | `psutil`, `pandas`, `matplotlib` (`pip install -r requirements.txt`); bag tools: `rosbags` (`pip install -r experiments/requirements-bags.txt`, Python ≥ 3.10, included in the ROS2 image) |
| Hardware | 2D LiDAR publishing on `/scan`, required only for recording bags and live runs |

On ROS images, install the Python packages with apt instead: `apt-get install -y python3-psutil python3-numpy python3-yaml python3-pandas python3-matplotlib` (the Docker images already include them). `summarize_metrics.py`, `compare_runs.py` and `compare_groups.py` use only the standard library.

The pipeline, metrics and analysis can be exercised without hardware.

> ROS1 Noetic does not run natively on macOS, and ROS2 Humble is not officially supported there either. On a Mac, use the Docker workflow below (pipeline testing only — a container cannot access USB/serial LiDAR hardware).

## Quick Start

Everything runs in Docker through `make` (`make help` lists all targets):

```
make images
make synthetic
make matrix RUNS=3
```

This builds `ros1-mapping:noetic` and `ros2-mapping:humble`, generates a synthetic bag with ground truth, runs ROS1 vs ROS2 three times each, and writes `results/report.md` with tables and figures.

The study's main commands:

```
make experiment STACK=ros2 ALGO=slam_toolbox RUNS=5 BAG=data/bags/corridor_01.bag
make matrix  BAG=data/bags/corridor_01.bag
make rmw     BAG=data/bags/corridor_01.bag
make image-ros2 DISTRO=jazzy
make distros BAG=data/bags/corridor_01.bag
make stress  BAG=data/bags/corridor_01.bag CPUS=1 MEMORY=2g
make long
make report  TAG=<run_tag> GROUP_BY=rmw
make check
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
make matrix BAG=data/bags/corridor_01.bag RUNS=5
```

The `make` targets call `experiments/run_matrix.sh`, which:

- Converts the bag to the other ROS format if needed and validates it
- Runs `RUNS` rounds of every variant in fresh containers, rotating the order each round
- Applies CPU/memory limits (`CPUS`, `CPU_SET`, `MEMORY`) and records them as the run's `condition`
- Tags every run with `RUN_TAG` and writes `results/reports/<RUN_TAG>/report.md` (+ `report.json`, `runs.csv`, figures) and `results/report.md`

Variants are `stack[:distro[:rmw]]`, e.g. `VARIANTS="ros1 ros2:humble:cyclonedds ros2:jazzy:zenoh" BAG=... ./experiments/run_matrix.sh`. Other options: `ALGO`, `RATE`, `SETTLE`, `COOLDOWN`, `CONDITION`, `GROUP_BY`, `BASELINE`, `BUILD=1`, `DOCKER_ARGS`.

### Middleware, distributions and stress

| Goal | Command |
|---|---|
| Fast DDS vs Cyclone DDS vs Zenoh | `make rmw BAG=...` (add `DISTRO=jazzy` for Jazzy) |
| Humble vs Jazzy | `make image-ros2 DISTRO=jazzy` once, then `make distros BAG=... [RMW=cyclonedds]` |
| Embedded-like CPU / memory | `make stress BAG=... CPUS=1 MEMORY=2g` or `CPU_SET=0,1` |
| Higher scan/TF rates | `make matrix BAG=... RATE=2`, or a synthetic bag with `--scan-hz 40 --beams 1080` |
| Memory growth over 30 min | `make long` |

Single runs take the same variables: `RMW=zenoh BAG=data/bags/x ./experiments/run_ros2.sh`, `CPU_SET=0 ./experiments/run_ros1.sh`. See [docs/metrics.md](docs/metrics.md#variants-stack-distribution-middleware).

### Single runs

```
BAG=data/bags/corridor_01.bag ./experiments/run_ros1.sh
BAG=data/bags/corridor_01 ./experiments/run_ros2.sh
```

Without `BAG`, the scripts run live against `/scan` for `DURATION` seconds (default 300). Each run:

- Creates `results/raw/<ros1|ros2>/<run_id>/`
- Starts SLAM (`ALGO=slam_toolbox` by default; `ALGO=gmapping` is available on ROS1 as a baseline) and waits until the node is up
- Dumps the parameters the node actually holds and fails if any differs from the config (`effective_params.json`)
- Replays the bag with `--clock` and `use_sim_time` (ROS2 uses `config/qos_overrides.yaml`), or runs for `DURATION` live
- Logs system-wide and per-process CPU/memory and network traffic (`cpu_mem.csv`, `proc_metrics.csv`, `net_io.csv`); fails if the logger produced no samples
- Records scan, map and TF timing events (`latency_events.csv`; `LOG_LATENCY=0` to disable)
- Saves the map before shutdown: `map.pgm` + `map.yaml` (ROS1 `map_saver`, ROS2 `/slam_toolbox/save_map`), the slam_toolbox pose graph (`/slam_toolbox/serialize_map` → `pose_graph.posegraph` + `.data`), and a rendered `map.png`
- Archives the parameter file and writes `run_meta.json` (stack, distro, RMW, variant, condition, algorithm, mode, bag, rate, tag, map/params/metrics status) and `run_manifest.json` (git commit and dirty flag, image id, sha256 of parameters/launch/bag, package versions, host and limits)
- Analyzes the run into `run_metrics.json`: latency, rates, drops, per-process resources, `trajectory.tum`, and ATE/RPE and map accuracy when the bag has a reference (`data/bags/<bag>.groundtruth.tum`, `data/bags/<bag>.reference.yaml`, or `REFERENCE_TRAJ` / `REFERENCE_MAP`)
- Stops every launched process group on exit

In replay mode a run fails unless a map was produced and saved (`REQUIRE_MAP=0` to relax); in both modes it fails on a parameter mismatch (`REQUIRE_PARAMS=0` to relax).

### Two machines

To measure transport overhead on a real network, run SLAM and the bag player on different machines with `ROLE=slam` and `ROLE=player`; see [docs/metrics.md](docs/metrics.md#two-machines-network--ipc-overhead).

Check the parameter files and the [mapping table](docs/parameter_mapping.md):

```
python3 experiments/check_params.py --check-doc
```

`BAG` accepts either form (`x.bag` or `x/`); the scripts pick the one matching their stack. Convert manually with `./experiments/convert_bag.sh data/bags/x.bag`.

## Analysis

Summarize a run (standard library only — runs in any ROS image):

```
python3 metrics/summarize_metrics.py results/raw/ros1/<run_id>/cpu_mem.csv
```

Analyze one run again (e.g. with another reference):

```
python3 metrics/analyze_run.py results/raw/ros2/<run_id> --reference-map data/bags/floorplan.yaml
```

Map accuracy and cross-run map consistency:

```
python3 metrics/map_quality.py compare results/raw/ros1/<run_id>/map.yaml data/bags/floorplan.yaml
python3 metrics/map_quality.py consistency --tag <run_tag>
```

Full report with tables and figures (also written automatically at the end of every batch):

```
make report TAG=<run_tag> GROUP_BY=rmw
```

Statistics across repeated runs (mean ± 95% CI, Mann-Whitney U, Cliff's delta; Kruskal-Wallis and Holm-adjusted p-values for three or more groups). Includes every headline metric from `run_metrics.json` that all selected runs have:

```
python3 metrics/compare_groups.py --tag <run_tag>
python3 metrics/compare_groups.py --tag <run_tag> --stack ros2 --group-by rmw
python3 metrics/compare_groups.py --tag <run_tag> --group-by variant --variant ros1-noetic,ros2-jazzy-zenoh
python3 metrics/compare_groups.py --tag a,b --group-by condition --variant ros2-humble-fastrtps
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

Plots are written as PNGs next to the source CSV. Replay runs also save `map.png` in the run folder.

## Reproducibility

This repository provides configuration files and experiment scripts to support reproducibility on similar mobile robot platforms equipped with a 2D LiDAR sensor. No proprietary firmware or internal company code is included.

Each experiment run generates a unique identifier, archives mapping parameters, logs system metrics, records its conditions in `run_meta.json` and its full provenance in `run_manifest.json` (code commit, Docker image id, input hashes, package versions, host and limits), and stores results in a structured, timestamped directory. Replay runs use recorded sensor data, so a batch can be re-run on another machine from the same bag.

- CI replays a synthetic bag with ground truth through ROS1 and through ROS2 Humble/Jazzy with each RMW, asserts that maps are produced and that accuracy is within bounds, and runs the full Docker/`make` path end to end. With a sample bag published as a release asset, CI also replays real robot data ([docs/dataset.md](docs/dataset.md)).
- `make dataset` packages bags, references, parameters and results with checksums for Zenodo; [docs/dataset.md](docs/dataset.md) covers the sample bag, the dataset DOI and the code DOI.

## Citation

See [CITATION.cff](CITATION.cff) (GitHub: "Cite this repository"). DOIs for the code and dataset will be added here once archived.

## Limitations

This study focuses on system-level behavior and mapping outcomes for one robot and environment. It does not provide statistical guarantees across diverse environments or evaluate large-scale fleet deployments.

Known limitations of the current pipeline:

- GMapping is ROS1-only; the comparison across stacks uses `slam_toolbox`.
- Latencies are measured at an observer process, so they include transport to it (identical for both stacks).
- ATE and map accuracy need a reference (ground truth, external tracking, floor plan); without one, only cross-run consistency is available.
- rmw_zenoh is installed only where the distribution provides a binary package; `RMW=zenoh` fails with a clear message otherwise.
- No experimental results are committed yet.

## Status

**v0.1.0 released; v0.2.0 in development.** The experiment pipeline, metrics, statistics, reports and reproducibility tooling are in place and exercised in CI on a synthetic bag with ground truth. Experimental runs on the real robot, results and analysis will be added in later releases. See [CHANGELOG.md](CHANGELOG.md).

## License

See [LICENSE](LICENSE).