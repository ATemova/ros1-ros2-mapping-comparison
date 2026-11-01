# Reproducibility

Three layers make a result reproducible, from strongest to weakest.

## 1. Published images (exact)

Every GitHub release publishes the three experiment images to GHCR for amd64 and arm64
(`.github/workflows/images.yml`), and attaches `images.lock` with their digests:

```
ghcr.io/atemova/ros1-ros2-mapping-comparison:ros1-noetic-<version>
ghcr.io/atemova/ros1-ros2-mapping-comparison:ros2-humble-<version>
ghcr.io/atemova/ros1-ros2-mapping-comparison:ros2-jazzy-<version>
```

To reproduce a release exactly, check out its tag and use its images:

```
git checkout v0.3.0
make pull VERSION=v0.3.0
make matrix BAG=data/bags/<bag>.bag
```

`make pull` tags them as `ros1-mapping:noetic`, `ros2-mapping:humble`, `ros2-mapping:jazzy`, so
every target uses them without rebuilding. This is the only way to get the same ROS package
versions later: the ROS apt repositories keep only the newest version of each package, so
rebuilding an image months later installs newer slam_toolbox, RMW and rosbag2 builds.

The first time the workflow runs, GHCR creates the package as private. Make it public once:
GitHub → your profile → Packages → `ros1-ros2-mapping-comparison` → Package settings →
Change visibility → Public.

## 2. Pinned base images (same OS layer)

`make lock` writes `docker/base-images.lock` with the multi-arch digest of `ros:noetic`,
`ros:humble` and `ros:jazzy`. Commit it; from then on `docker/build.sh` (used by `make` and
`run_matrix.sh`) builds on exactly those base images. Refresh deliberately with `make lock`.
ROS packages installed on top still come from the live apt repository (see layer 1).

## 3. Per-run record (audit)

Every run writes `run_manifest.json`: commit and dirty flag, image tag, id, registry digests
and base image, sha256 of the parameter file, launch file, QoS overrides and bag, versions of
the ROS packages that matter, Python libraries, host, CPU/memory limits and the ROS/DDS/Zenoh
environment. The report's *Provenance* section summarises it, and
[data-format.md](data-format.md) defines it.

## Architectures

Images, CI and the runner support amd64 and arm64 (e.g. a Raspberry Pi 4/5 or Jetson-class
robot computer). Each run records `arch`; runs of different architectures are never pooled,
and `compare_groups.py --group-by arch` compares the same variant across machines.

On the robot computer itself, either pull the arm64 images (`make pull`) or run natively
with ROS installed: `BAG=... ./experiments/run_ros1.sh`.

## Checklist for a published result

- [ ] `git status` clean (manifests record `dirty`)
- [ ] Release tagged; images published; `images.lock` attached
- [ ] `make validate` passes on the results being published
- [ ] Dataset archived with `make dataset` and its DOI in the README and `CITATION.cff`
