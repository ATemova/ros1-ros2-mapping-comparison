#!/bin/bash
set -e

echo "Starting ROS2 mapping experiment"

# Experiment configuration
EXPERIMENT_ID=$(date +"%Y%m%d_%H%M%S")
OUTPUT_DIR="results/raw/ros2/${EXPERIMENT_ID}"
DURATION=300

mkdir -p "${OUTPUT_DIR}"

echo "Experiment ID: ${EXPERIMENT_ID}"
echo "Output directory: ${OUTPUT_DIR}"

# Source ROS2
source /opt/ros/humble/setup.bash

# Start mapping
ros2 launch ros2 mapping.launch.py &
MAPPING_PID=$!
sleep 5

# Start metrics logging
python3 metrics/cpu_memory_logger.py \
  --output "${OUTPUT_DIR}/cpu_mem.csv" &
METRICS_PID=$!

# Run experiment
sleep ${DURATION}

# Stop processes
kill ${METRICS_PID}
kill ${MAPPING_PID}

echo "ROS2 experiment finished"