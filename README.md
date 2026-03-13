<p align="center">
  <img src="https://img.shields.io/badge/ROS1-Noetic-blue?style=flat-square&logo=ros" />
  <img src="https://img.shields.io/badge/ROS2-Humble-blueviolet?style=flat-square&logo=ros" />
  <img src="https://img.shields.io/badge/Sensor-2D%20LiDAR-informational?style=flat-square" />
  <img src="https://img.shields.io/badge/Platform-Mobile%20Robot-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/Study-System--Level%20Comparison-success?style=flat-square" />
  <img src="https://img.shields.io/badge/Status-Active%20Development-yellow?style=flat-square" />
</p>

# ROS1 vs ROS2 Mapping Comparison

This repository contains experimental scripts, configuration files, and analysis tools used in the study:

**“A Practical Comparison of ROS1 and ROS2 Mapping Pipelines on a Real Mobile Robot”**

The objective of this work is to empirically evaluate the differences between ROS1 and ROS2 mapping pipelines under controlled, repeatable real-world conditions.


## Overview

The Robot Operating System (ROS) is widely adopted in mobile robotics. While ROS1 has been the dominant middleware for many years, ROS2 introduces architectural changes aimed at improving performance, reliability, and scalability.
As robotics systems transition from ROS1 to ROS2, it becomes essential to understand how these architectural differences affect practical deployment scenarios such as real-time mapping.
This project provides a system-level comparison of ROS1 and ROS2 mapping pipelines using identical hardware, sensor configurations, and experimental conditions on a real mobile robot.

## Experimental Scope

The comparison focuses on:

- System-level performance (CPU and memory utilization)  
- Runtime stability during mapping execution  
- Qualitative consistency of generated maps  

Experiments are conducted on a real mobile robot operating in a controlled indoor environment. All runs follow fixed trajectories and identical environmental conditions to ensure a fair and reproducible comparison.

## Reproducibility

This repository provides configuration files and experiment scripts to support reproducibility on similar mobile robot platforms equipped with a 2D LiDAR sensor.
No proprietary firmware or internal company code is included.

Each experiment run:
- Generates a unique experiment identifier  
- Archives mapping parameters  
- Logs system metrics (CPU and memory usage)  
- Stores results in a structured directory format  

All experiment outputs are timestamped to enable traceability and cross-run comparison.

## Running Experiments

Experiments are executed using the provided shell scripts:

- `experiments/run_ros1.sh`  
- `experiments/run_ros2.sh`  

Each script automatically:
- Initializes the mapping pipeline  
- Records system resource usage  
- Archives configuration parameters  
- Stores logs and generated maps  

## Limitations

This study focuses on system-level behavior and qualitative mapping outcomes.

It does not attempt to:
- Benchmark SLAM accuracy quantitatively  
- Provide statistical guarantees across diverse environments  
- Evaluate large-scale deployment scenarios  

These aspects are considered future work.

## Status

This project is under active development.  
Results, figures, and detailed analysis will be added as experiments are completed and evaluated.
