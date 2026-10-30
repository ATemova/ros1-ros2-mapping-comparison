# Metrics

Every run directory (`results/raw/<stack>/<run_id>/`) gets raw logs from the run and a
`run_metrics.json` computed afterwards by `metrics/analyze_run.py`. Its `summary` block
holds the headline numbers that `metrics/compare_groups.py` compares between ROS1 and
ROS2. A metric only appears in the comparison when every selected run has it.

## Raw files

| File | Written by | Content |
|---|---|---|
| `cpu_mem.csv` | `metrics/cpu_memory_logger.py` | System-wide CPU % (of all cores) and used memory, 1 Hz |
| `proc_metrics.csv` | same | Per role: process count, CPU % (of **one** core, can exceed 100), RSS, 1 Hz |
| `net_io.csv` | same | Cumulative bytes/packets per network interface, 1 Hz |
| `latency_events.csv` | `metrics/ros_latency_logger.py` | One row per received scan, map and relevant TF (map→odom, odom→base) |
| `trajectory.tum` | `metrics/analyze_run.py` | Online SLAM pose estimate (TUM format, for `evo`) |
| `map.pgm`, `map.yaml`, `pose_graph.*` | runner (map saving) | Final map and slam_toolbox pose graph |

## Process roles

Processes are grouped by command line (`--role NAME=REGEX` to change):

| Role | ROS1 | ROS2 |
|---|---|---|
| `slam` | `sync_slam_toolbox_node` / `slam_gmapping` | `sync_slam_toolbox_node` |
| `middleware` | `rosmaster`, `rosout` | `ros2` CLI daemon when running, Zenoh router (`rmw_zenohd`) with `RMW=zenoh` (DDS has no master; discovery runs inside each process) |
| `launch` | `roslaunch` | `ros2 launch` |
| `bag_player` | `rosbag play` | `ros2 bag play` |
| `latency_logger` | `ros_latency_logger.py` | same |

`slam_cpu_*` is the cleanest middleware comparison: same algorithm, same parameters, same
input, and the SLAM process contains each stack's client library (roscpp vs rclcpp + DDS).

## Headline metrics (`summary`)

### Resources

| Key | Definition |
|---|---|
| `slam_cpu_mean`, `slam_cpu_p95` | SLAM process CPU, % of one core, over 1 s samples |
| `slam_rss_mean_mb`, `slam_rss_peak_mb` | SLAM process resident memory |
| `slam_rss_growth_mb`, `slam_rss_slope_mb_per_min` | SLAM RSS last − first sample, and least-squares trend; use long runs (`make long`) |
| `middleware_cpu_mean`, `middleware_rss_mean_mb` | Middleware processes (see roles) |
| `launch_cpu_mean`, `bag_player_cpu_mean` | Launch and bag player processes |
| `net_total_mb`, `net_rate_kBps` | Bytes sent + received on all interfaces during the run |

On one machine, ROS1 TCPROS goes over loopback (`lo`) or the container interface, while
Fast DDS uses shared memory by default, so `net_*` is near zero for ROS2. That difference
is a property of the transports, not a measurement error. Use the two-machine setup for
traffic that actually crosses the network.

### Timing (from `latency_events.csv`)

Wall clock = receive time at the logger; ROS clock = simulated time in replay.

| Key | Definition | Clock |
|---|---|---|
| `scan_drop_rate` | 1 − scans received / scans in the bag (replay only) | – |
| `scan_gap_drop_rate` | missing scans inferred from gaps in scan header stamps | – |
| `scan_to_map_latency_ms` (+`_p95_ms`) | `/map` receive time − receive time of the newest scan before it: how stale the published map is relative to the input | wall |
| `tf_update_latency_ms` (+`_p95_ms`) | time a new map→odom correction is received − receive time of the newest scan before it: scan-to-pose-correction latency | wall |
| `map_period_s` | mean interval between `/map` messages (configured: `map_update_interval`) | ROS |
| `map_period_jitter_ms` | standard deviation of that interval | ROS |
| `map_age_ms` | `/map` receive time − its header stamp | ROS |
| `map_period_wall_s`, `map_period_wall_jitter_ms` | the same on the wall clock; slam_toolbox on ROS2 runs its map timer on wall time, so with `RATE` ≠ 1 it differs from the ROS-clock period | wall |
| `time_to_first_map_s` | first `/map` (ROS-clock receive time) − first scan's header stamp | ROS |

Map and TF events count only while input is flowing (until 1 s after the last scan), so
maps published after the bag ended do not inflate latency or jitter. Events received before
the first `/clock` message (ROS time 0) are excluded from ROS-clock metrics.

The logger subscribes with the same QoS as SLAM (ROS2: sensor-data QoS for scans,
reliable + transient-local for the map), so the drops it sees are those a SLAM-like
subscriber sees. It is an extra subscriber to `/map` on both stacks; for CPU-only runs set
`LOG_LATENCY=0`. Both latency metrics include transport to the logger and are
upper bounds on processing time; they compare stacks fairly because both pay the same
measurement path.

### Trajectory (ATE / RPE)

The estimated trajectory is the pose SLAM believed online: latest map→odom received so far
composed with odom→base at each odom stamp. It is compared with a reference trajectory:

| Key | Definition |
|---|---|
| `ate_rmse_m` | Absolute trajectory error, RMSE of position after SE(3) alignment without scale (`evo_ape --align`) |
| `rpe_trans_rmse_m`, `rpe_rot_rmse_deg` | Relative pose error between consecutive associated poses (`evo_rpe`, delta 1 frame) |

Association follows `evo` (nearest timestamp within 10 ms). The implementation in
`metrics/trajectory.py` matches evo 1.38 to ~1e-13; `trajectory.tum` can be fed to `evo`
directly for plots: `evo_ape tum reference.tum trajectory.tum --align --plot`.

Reference options:

- **Synthetic bag**: `data/bags/synthetic.groundtruth.tum` (exact, generated with the bag).
- **External tracking** (motion capture, total station, UWB): export TUM, save as
  `data/bags/<bag>.groundtruth.tum` or pass `REFERENCE_TRAJ=...`.
- **Offline reference run**: replay the same bag at a low rate with more conservative
  settings (e.g. `RATE=0.25`), then use that run's `trajectory.tum` as reference. This
  measures agreement with a best-effort solution, not absolute accuracy; say so when reporting.

### Map quality

`metrics/map_quality.py compare test.yaml reference.yaml` aligns the test map to the
reference (rotation search, ±10° by default, plus FFT translation search on occupied cells)
and reports on the reference grid:

| Key | Definition |
|---|---|
| `map_cell_accuracy` | share of cells known in both maps that have the same class (free/occupied) |
| `map_wall_f1` | F1 of occupied cells with ±1 cell tolerance (precision: test walls near a reference wall; recall: reference walls near a test wall) |
| `map_wall_error_m` | mean distance from test walls to the nearest reference wall (alignment and sharpness) |
| `map_completeness_m` | mean distance from reference walls to the nearest test wall (missing structure) |

Also in `run_metrics.json`: strict `occ_iou`, F1 at ±2 cells, known-area ratio, the
alignment transform. Distances are capped at 1 m.

Reference options:

- **Synthetic bag**: `data/bags/synthetic.reference.yaml` (the floor plan of the simulated room).
- **Floor plan**: rasterize it to a map_server map (walls black, free white, unknown grey,
  resolution and origin in the .yaml), save as `data/bags/<bag>.reference.yaml` or pass
  `REFERENCE_MAP=...`. If its frame is not the SLAM map frame, increase the rotation search
  with `analyze_run.py --ref-max-angle 180`.

**Cross-run consistency** needs no reference: `map_quality.py consistency --tag T` compares
all pairs of saved maps in a batch (within ROS1, within ROS2, ROS1 vs ROS2). `run_matrix.sh`
appends it to the batch report.

## Two machines (network / IPC overhead)

On one machine, both stacks avoid the network, so transport differences barely show.
Running the bag player and SLAM on different machines puts `/scan`, `/tf`, `/odom` and
`/clock` on the wire, which is where TCPROS and DDS differ.

Both machines: same repository checkout, same bag (both forms), host networking.

ROS1 (the master runs on the SLAM machine, `10.0.0.1` here; the player is `10.0.0.2`):

```
ROLE=slam ROS_IP=10.0.0.1 BAG=data/bags/corridor_01.bag RUN_TAG=net_ros1 ./experiments/run_ros1.sh
```
```
ROLE=player ROS_IP=10.0.0.2 ROS_MASTER_URI=http://10.0.0.1:11311 BAG=data/bags/corridor_01.bag RUN_TAG=net_ros1 ./experiments/run_ros1.sh
```

ROS2 (same `ROS_DOMAIN_ID` on both, multicast allowed on the LAN):

```
ROLE=slam ROS_DOMAIN_ID=42 BAG=data/bags/corridor_01 RUN_TAG=net_ros2 ./experiments/run_ros2.sh
```
```
ROLE=player ROS_DOMAIN_ID=42 BAG=data/bags/corridor_01 RUN_TAG=net_ros2 ./experiments/run_ros2.sh
```

In Docker, add `--network host` and pass the variables with `-e`. Start the slam side first;
it prints `Ready` and waits up to `CLOCK_WAIT` seconds (default 600) for `/clock`, then
finishes `CLOCK_IDLE` seconds after the player stops. Both sides write a run folder; the
player's (`role: player`) holds the sender-side CPU and network numbers and is excluded from
`compare_groups.py`. Compare distributed runs with `--tag`, as for local ones. Local and
distributed runs are never mixed, because `role` is part of the run condition.

Keep clocks synchronized (NTP/chrony) if you compare wall-clock latencies across machines.
All latencies here are measured on the SLAM machine, so they do not depend on it.

## Variants: stack, distribution, middleware

Every run records `stack`, `ros_distro`, `rmw` and a `variant` label
(`ros1-noetic`, `ros2-humble-fastrtps`, `ros2-jazzy-zenoh`, ...).

| Dimension | How to set it | Notes |
|---|---|---|
| ROS2 middleware | `RMW=fastrtps` (default) / `cyclonedds` / `zenoh` | Zenoh starts `rmw_zenohd` for the run; for two machines point the player at it with `ZENOH_CONFIG_OVERRIDE='connect/endpoints=["tcp/<slam-ip>:7447"]'` and set `ZENOH_ROUTER=external` on any side that should not start its own router |
| ROS2 distribution | image `ros2-mapping:<distro>` (`make image-ros2 DISTRO=jazzy`) | From Jazzy on, slam_toolbox is a lifecycle node; the launch file configures and activates it |
| Stack | `run_ros1.sh` / `run_ros2.sh` | ROS1 is always TCPROS |

Noetic reached end of life in May 2025, Humble is supported until May 2027 and Jazzy until
May 2029, which is why the study covers both ROS2 LTS releases. Newer distributions
(e.g. Lyrical) work the same way: `DISTRO=<name>` builds the image and the lifecycle launch path applies.

`compare_groups.py --group-by stack|rmw|ros_distro|variant|condition` compares any of these;
everything else (algorithm, bag, rate, condition, ...) must match or the script refuses to pool.
With three or more groups the report adds a Kruskal–Wallis test and Holm-adjusted pairwise p-values.

## Conditions (stress)

| Stressor | How | Recorded as |
|---|---|---|
| CPU cores | `CPU_SET=0,1` (container `--cpuset-cpus`, or `taskset` natively) | `condition: cpus2` |
| CPU quota | `CPUS=1.5` (container `--cpus`, i.e. cgroup `cpu.max`) | `condition: quota1.5` |
| Memory | `MEMORY=2g` (container `--memory`) | `condition: mem2048M` |
| Scan / TF rate | `RATE=2`, `RATE=4` (faster playback), or a high-rate synthetic bag (`--scan-hz 40 --beams 1080`) | `rate`, bag id |
| Duration | `make long` (30 min synthetic loop bag) or a long recording | bag id; read `slam_rss_slope_mb_per_min` |

The condition is derived from the limits that actually apply inside the run (cgroup and
CPU affinity), so a mis-applied limit shows up as `default`. `CONDITION=<label>` overrides it,
e.g. `CONDITION=rpi4-like` for `CPUS=4 MEMORY=4g`. Compare conditions of one variant with
`compare_groups.py --tag a,b --group-by condition --variant ros2-humble-fastrtps`.

## Reproducibility record

Each run folder has `run_manifest.json`: git commit and dirty flag, Docker image tag and id,
sha256 of the parameter file, launch file, QoS overrides and bag, versions of the ROS
packages that matter (slam_toolbox, rclcpp/roscpp, RMWs, rosbag2), Python libraries, host
CPU/memory/OS and the CPU/memory limits in force, and the ROS/DDS/Zenoh environment variables.
The report's *Provenance* section summarises them.

## Reports

`make report TAG=<tag> [GROUP_BY=...]` (or `metrics/make_report.py`) writes
`results/reports/<tag>/report.md` and a copy at `results/report.md`: setup per group (image,
distro, RMW, slam_toolbox version, condition), the statistics table, figures (per-run metric
distributions, SLAM CPU and RSS over time, trajectories against the reference, maps),
map consistency, provenance and links to every run. `run_matrix.sh` (and every `make`
experiment target) generates it at the end of a batch.
