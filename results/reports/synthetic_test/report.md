## ROS1 vs ROS2

Algorithm: `slam_toolbox` · mode: `replay` · bag: `synthetic` · rate: `2.0` · runs: ROS1 n=3, ROS2 n=3

| Metric | ROS1 mean ± 95% CI | ROS2 mean ± 95% CI | Δ ROS2−ROS1 | p (MWU) | Cliff's δ |
|---|---|---|---|---|---|
| CPU mean (%) | 0.88 ± 0.10 | 1.70 ± 0.29 | 0.82 (93.8%) | 0.100 | 1.00 (large) |
| CPU p95 (%) | 1.80 ± 0.52 | 7.02 ± 0.25 | 5.22 (289.5%) | 0.100 | 1.00 (large) |
| Memory mean (MB) | 676.75 ± 28.30 | 599.90 ± 18.52 | -76.85 (-11.4%) | 0.100 | -1.00 (large) |
| Memory peak (MB) | 688.91 ± 15.13 | 635.68 ± 14.96 | -53.23 (-7.7%) | 0.100 | -1.00 (large) |
| Memory growth (MB) | -11.54 ± 65.60 | 0.10 ± 52.00 | 11.64 (-100.9%) | 0.700 | 0.33 (medium) |

Per-run metrics are the run's mean/p95/peak/growth; the table summarises them across runs. Cliff's δ > 0 means ROS2 is higher.

> Only 3 run(s) in the smaller group. With fewer than 4 runs per group the two-sided Mann-Whitney test cannot reach p < 0.05; collect at least 5 per stack.
