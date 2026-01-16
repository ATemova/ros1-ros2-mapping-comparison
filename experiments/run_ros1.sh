#!/bin/bash
set -e

echo "Starting ROS1 mapping experiment"

# Experiment configuration
EXPERIMENT_ID=$(date +"%Y%m%d_%H%M%S")
OUTPUT_DIR="results/raw/ros1/${EXPERIMENT_ID}"
DURATION=300

mkdir -p "${OUTPUT_DIR}"

echo "Experiment ID: ${EXPERIMENT_ID}"
echo "Output directory: ${OUTPUT_DIR}"

# Start roscore
roscore &
ROSCORE_PID=$!
sleep 5

# Start mapping
roslaunch ros1 mapping.launch &
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
kill ${ROSCORE_PID}

echo "ROS1 experiment finished"