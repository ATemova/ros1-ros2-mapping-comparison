#!/usr/bin/env bash
# Run one ROS2 mapping experiment. See experiments/common.sh for the environment variables.
STACK=ros2
# shellcheck source=experiments/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
run_experiment
