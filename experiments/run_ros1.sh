#!/bin/bash

echo "Starting ROS1 mapping experiment"

# Experiment configuration
EXPERIMENT_ID=$(date +"%Y%m%d_%H%M%S")
OUTPUT_DIR="results/raw/ros1/${EXPERIMENT_ID}"
DURATION=300
ROS_VERSION="ROS1"

mkdir -p "${OUTPUT_DIR}"

# Archive parameters
cp ros1/params/*.yaml "${OUTPUT_DIR}/" 2>/dev/null || true

echo "Experiment ID: ${EXPERIMENT_ID}"
echo "Output directory: ${OUTPUT_DIR}"
echo "Duration: ${DURATION}s"

# Cleanup handler
cleanup() {
  echo "Stopping experiment processes..."
  kill ${METRICS_PID} ${MAPPING_PID} ${ROSCORE_PID} 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Start ROS core
roscore &
ROSCORE_PID=$!
sleep 5

# Start mapping
roslaunch ros1 mapping.launch &
MAPPING_PID=$!
sleep 5

# Start metrics logging
python3 metrics/cpu_memory_logger.py \
  --output "${OUTPUT_DIR}/cpu_mem.csv" \
  --experiment_id "${EXPERIMENT_ID}" \
  --ros_version "${ROS_VERSION}" &
METRICS_PID=$!

# Run experiment
sleep ${DURATION}

echo "ROS1 experiment completed"