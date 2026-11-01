# Hardware and environment

Fill this in before recording the dataset; the paper's setup section and the Zenodo record
are written from it. Per-run details (CPU model, memory, kernel, limits, package versions)
are recorded automatically in each run's `run_manifest.json`; this page covers what the
pipeline cannot detect.

## Robot

| Item | Value |
|---|---|
| Robot model | |
| Drive (differential, ...) | |
| Wheel odometry source and rate | |
| Onboard computer (model) | |
| CPU / cores / clock | |
| Architecture (`uname -m`) | |
| RAM | |
| Storage (type) | |
| OS and kernel | |
| Power mode / governor during experiments | |

## Sensor

| Item | Value |
|---|---|
| 2D LiDAR model | |
| Scan rate (Hz) | |
| Beams per scan / angular resolution | |
| Range (min / max, m) | |
| Mounting (height, offset from base_link) | |
| Driver package and version | |
| Connection (USB / Ethernet) | |

## Software on the robot

| Item | Value |
|---|---|
| ROS1 setup (native / Docker image) | |
| ROS2 setup (native / Docker image) | |
| Driver stack used while recording | |
| Repository version / commit used for recording | |

## Environment

| Item | Value |
|---|---|
| Location type (corridor, office, ...) | |
| Approximate size (m) | |
| Floor | |
| Dynamic objects during recording | none (protocol) |
| Lighting | consistent (protocol) |
| Reference available | floor plan / ground truth / none |
| How the reference was produced | |

## Machines for replay and two-machine runs

| Role | Machine | CPU / cores | RAM | Arch | OS | Network link |
|---|---|---|---|---|---|---|
| SLAM | | | | | | |
| Player | | | | | | |

## Publication check

- [ ] Recording location and floor plan cleared for publication by the owner/employer
- [ ] No people, screens or documents identifiable in the data (2D LiDAR only: usually none)
- [ ] Data licence chosen for the Zenodo record
