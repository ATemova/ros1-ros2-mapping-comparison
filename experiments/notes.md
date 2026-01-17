# Experiment Notes

## Environment
- Indoor office corridor
- Static environment (no moving obstacles)
- Consistent lighting conditions

## Robot Motion
- Constant linear velocity
- Fixed trajectory for all runs

## Experiment Duration
- 5 minutes per run

## Map Saving
- Maps are saved automatically at the end of each experiment run
- ROS1 maps are saved using map_server
- ROS2 maps are saved using slam_toolbox services

## Map Evaluation
- Mapping quality is evaluated based on consistency across multiple runs
- Qualitative comparison is performed using occupancy grid images

## Notes
- All experiments are executed for a fixed duration.
- The robot follows a repeatable trajectory during each run.
- ROS1 and ROS2 experiments are conducted under identical conditions.