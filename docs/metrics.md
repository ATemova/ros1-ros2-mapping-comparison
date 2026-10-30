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
| `middleware` | `rosmaster`, `rosout` | `ros2` CLI daemon when running (ROS2 has no master; DDS discovery runs inside each process) |
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
| `time_to_first_map_s` | first `/map` − first scan | ROS |

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
