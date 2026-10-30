#!/usr/bin/env bash
# Run one ROS1 mapping experiment. See experiments/common.sh for the environment variables.
STACK=ros1
# shellcheck source=experiments/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
run_experiment
