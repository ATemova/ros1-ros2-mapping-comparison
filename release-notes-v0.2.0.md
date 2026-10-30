Complete experiment pipeline for comparing ROS1 and ROS2 mapping. No results from the real robot yet; those come with the dataset in the next release.

## Highlights

- **Fair comparison by design.** Both stacks run slam_toolbox (sync) with one shared parameter file. The parameters each node actually holds are verified at runtime, and both replay the same recorded bag. Every condition is repeated and compared statistically (mean ± 95% CI, Mann-Whitney U, Cliff's δ; Kruskal-Wallis and Holm for 3+ groups).
- **Metrics.** Per-process CPU/RSS (SLAM node, middleware, launch, bag player) and network traffic; scan→map and scan→TF latency; map period and jitter; time to first map; scan drops; ATE/RPE (matches evo); map accuracy against a reference and map consistency across runs.
- **Beyond ROS1 vs ROS2.** Fast DDS vs Cyclone DDS vs Zenoh, Humble vs Jazzy (lifecycle slam_toolbox handled), stress conditions (CPU cores or quota, memory limit, higher scan rates, 30-minute runs), and two-machine runs for network overhead.
- **Reproducibility.** One-command `make` targets, a `run_manifest.json` per run (commit, image id, input hashes, package versions, host and limits), a generated `results/report.md` with figures, automatic map saving, and Zenodo/CITATION metadata.
- **CI.** A synthetic bag with ground truth is replayed through ROS1 Noetic and through ROS2 Humble and Jazzy with every RMW. CI asserts maps, parameters and accuracy bounds, then builds the comparison report. A Docker end-to-end job runs through `make`.

## Upgrading from v0.1.0

- Parameters moved from `ros1/params` and `ros2/params` to `config/` (`docs/parameter_mapping.md`).
- Rebuild the images: `make images` (now tagged `ros1-mapping:noetic` and `ros2-mapping:<distro>`).
- Start with `make help`, then `make synthetic && make matrix RUNS=3`.

Full list of changes: [CHANGELOG.md](https://github.com/ATemova/ros1-ros2-mapping-comparison/blob/v0.2.0/CHANGELOG.md)
