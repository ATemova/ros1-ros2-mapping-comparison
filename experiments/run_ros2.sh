#!/bin/bash

echo "Starting ROS2 mapping experiment"

# Source ROS2
source /opt/ros/humble/setup.bash

# Start mapping
ros2 launch ros2 mapping.launch.py &
MAPPING_PID=$!

# Start metrics
python3 metrics/cpu_memory_logger.py --output results/raw/ros2_cpu_mem.csv &
METRICS_PID=$!

# Run experiment
sleep 300

# Stop everything
kill $METRICS_PID
kill $MAPPING_PID

echo "ROS2 experiment finished"