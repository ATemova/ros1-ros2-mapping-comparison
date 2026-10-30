# Experiment Protocol

## Design

The comparison isolates the **middleware**: both stacks run the same SLAM algorithm
with the same parameters on the same recorded sensor data.

| Factor | Controlled by |
|---|---|
| Algorithm | `slam_toolbox` (synchronous mode) on both ROS1 Noetic and ROS2 Humble |
| Parameters | One shared file, `config/slam_toolbox.yaml`, loaded unchanged by both launch files |
| Sensor input | One recorded bag, replayed to both stacks (`ROS1 .bag` and its converted ROS2 form) |
| Time | Simulated time from the bag (`--clock`, `use_sim_time`) |
| Replay QoS (ROS2) | `config/qos_overrides.yaml` for every replayed topic |
| Order effects | Counterbalanced rounds (ROS1→ROS2, then ROS2→ROS1, ...) in `run_matrix.sh` |
| Environment | Fresh container per run; optional CPU/memory pinning via `DOCKER_ARGS` |

GMapping is kept as a **ROS1-only baseline** (`ALGO=gmapping`, `config/gmapping.yaml`).
The ROS2 GMapping ports are unofficial and do not expose the same parameters, so a
ROS2 GMapping run would not be parameter-equivalent.

## Recording the bag

1. Indoor office corridor, static environment, consistent lighting.
2. Stop any SLAM node. Start the robot base and LiDAR drivers only.
3. `experiments/record_bag.sh corridor_01` while driving the fixed trajectory at constant
   linear velocity. Records `/scan /odom /tf /tf_static` for `DURATION` seconds (default 300).
4. Validate: `python3 experiments/inspect_bag.py data/bags/corridor_01.bag`
   (fails if `/tf` already contains `map->odom`, i.e. SLAM was running).
5. Record several bags (different days / trajectories) if the study should generalise
   beyond one dataset; each bag is analysed as its own condition.

## Replay runs

- `BAG=data/bags/corridor_01.bag RUNS=5 ./experiments/run_matrix.sh`
- At least **5 runs per stack** per condition. With fewer than 4 per group the two-sided
  Mann-Whitney test cannot reach p < 0.05.
- Keep the host idle during a batch; use `DOCKER_ARGS="--cpuset-cpus=2,3"` to pin cores.
- Playback rate 1.0 for the reported results. Higher rates are for stress tests only and
  are reported as a separate condition.

## Live runs

Live runs (`./experiments/run_ros1.sh` without `BAG`) are kept as a sanity check that
replay behaviour matches the real robot. They are not used for the statistical comparison,
since trajectory and environment cannot be repeated exactly.

## Analysis

- Per run (`run_metrics.json`, definitions in `docs/metrics.md`): system and per-process
  CPU/RSS, network traffic, scan→map and scan→TF latency, map period and jitter, time to
  first map, scan drops, ATE/RPE and map accuracy against the bag's reference.
- Across runs: mean ± 95% CI per stack, ROS2−ROS1 difference, two-sided Mann-Whitney U,
  Cliff's delta (`metrics/compare_groups.py`), and pairwise map consistency
  (`metrics/map_quality.py consistency`).

## References for accuracy

- Record ground truth alongside the bag when possible (motion capture, total station) and
  save it as `data/bags/<bag>.groundtruth.tum`.
- Draw or rasterize the floor plan of the corridor as `data/bags/<bag>.reference.yaml/.pgm`.
- Without either, report cross-run consistency and, if useful, agreement with an offline
  reference run (clearly labelled as such).

## Middleware and distribution experiments

- Same bag, same parameters; only the RMW (`make rmw`) or the distribution (`make distros`)
  changes. Report each as its own comparison (group by `rmw` / `ros_distro`).
- ROS1 vs ROS2 is reported against ROS2's default RMW (Fast DDS) on Humble; the other RMWs
  and Jazzy are separate rows of the variant report, not pooled into "ROS2".

## Stress conditions

- CPU: `CPUS` (quota) or `CPU_SET` (cores); memory: `MEMORY`. Choose limits that match a
  target board (e.g. `CPUS=4 MEMORY=4g CONDITION=rpi4-like`) and keep them for all variants.
- Rate: `RATE=2` and `RATE=4` replay the same bag faster (scan and TF rates scale together);
  for a higher LiDAR rate only, use a synthetic bag with `--scan-hz`.
- Duration: `make long` (30 min loop bag, 3 runs per stack); report `slam_rss_slope_mb_per_min`.
- Conditions are recorded per run and never pooled; compare them with `--group-by condition`.

## Network experiments

Same protocol with `ROLE=slam` / `ROLE=player` on two machines on the same switch
(docs/metrics.md). Report local and distributed results as separate conditions.

## Map saving

At the end of every run in which a `/map` was received, before anything is stopped:

| | Occupancy grid | Pose graph (slam_toolbox) |
|---|---|---|
| ROS1 | `rosrun map_server map_saver -f <run>/map` | `rosservice call /slam_toolbox/serialize_map` |
| ROS2 | `ros2 service call /slam_toolbox/save_map` (uses `nav2_map_server`) | `ros2 service call /slam_toolbox/serialize_map` |

Output per run: `map.pgm`, `map.yaml`, `map.png`, `pose_graph.posegraph`, `pose_graph.data`.
CPU/memory logging stops before saving, so map export is not counted in the metrics.

## Run validity

A run fails (non-zero exit, `exit_status` in `run_meta.json`) when:

- the SLAM package is missing or the node does not come up (no fallback)
- the node holds a parameter value that differs from the config file
- `psutil` is unavailable, the logger exits early, or `cpu_mem.csv` has no samples
- replay mode: the bag player fails, or no map is received and saved

`compare_groups.py` ignores failed runs by default.

## Known gaps (next iterations)

- Latency is observed from a separate subscriber process (includes transport to it).
