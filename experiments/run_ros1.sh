#!/bin/bash

echo "Starting ROS1 mapping experiment"

# Start roscore
roscore &
ROSCORE_PID=$!
sleep 5

# Start mapping
roslaunch ros1 mapping.launch &
MAPPING_PID=$!

# Start metrics
python3 metrics/cpu_memory_logger.py --output results/raw/ros1_cpu_mem.csv &
METRICS_PID=$!

# Run experiment for fixed time
sleep 300

# Stop everything
kill $METRICS_PID
kill $MAPPING_PID
kill $ROSCORE_PID

echo "ROS1 experiment finished"