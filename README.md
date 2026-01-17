# ROS1 vs ROS2 Mapping Comparison

This repository contains experiment scripts, configuration files, and analysis tools used in the study:

**“A Practical Comparison of ROS1 and ROS2 Mapping Pipelines on a Real Mobile Robot”**

The goal of this work is to empirically evaluate differences between ROS1 and ROS2 mapping pipelines under controlled, repeatable real-world conditions.

## Overview

The Robot Operating System (ROS) is widely used in mobile robotics. While ROS1 has been the dominant middleware for many years, ROS2 introduces architectural changes intended to improve performance, reliability, and scalability. As robotics systems transition from ROS1 to ROS2, it is important to understand how these changes affect practical deployment scenarios such as mapping.

This project provides a system-level comparison of ROS1 and ROS2 mapping pipelines using identical hardware, sensor configurations, and experimental conditions on a real mobile robot.

## Experimental Scope

The comparison focuses on:
- system-level performance (CPU and memory usage)
- stability during mapping execution
- qualitative consistency of generated maps

Experiments are conducted on a real mobile robot operating in an indoor environment. All runs follow fixed trajectories and controlled conditions to ensure fair comparison.

## Reproducibility

This repository provides configuration files and experiment scripts to support reproducibility on similar mobile robot platforms equipped with a 2D LiDAR sensor. No proprietary robot firmware or internal company code is included.

Each experiment run is logged with timestamped outputs and archived parameters to enable traceability and comparison across runs.

## Status

This project is under active development. Results and figures will be added as experiments are completed and analyzed.

## Running Experiments

Experiments are executed using the provided shell scripts:

- `experiments/run_ros1.sh`
- `experiments/run_ros2.sh`

Each script automatically:
- creates a unique experiment identifier
- archives mapping parameters
- logs CPU and memory usage
- stores outputs in a structured results directory

## Limitations

This study focuses on system-level behavior and qualitative mapping outcomes. It does not aim to benchmark SLAM accuracy or provide statistical guarantees across diverse environments. These aspects are considered future work.