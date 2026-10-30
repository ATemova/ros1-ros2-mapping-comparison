"""ROS2 mapping launch.

Loads config/slam_toolbox.yaml, the same flat parameter file ROS1 loads, and passes
it to slam_toolbox as a dict, so both stacks run with identical parameters.

Launch arguments:
    algo          slam_toolbox (only option on ROS2)
    use_sim_time  true for bag replay
    config_dir    directory holding slam_toolbox.yaml (default: <repo>/config)
"""

import os

import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

SUPPORTED_ALGOS = ("slam_toolbox",)


def _default_config_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir, "config"))


def _as_bool(text):
    return str(text).strip().lower() in ("1", "true", "yes", "on")


def _setup(context):
    algo = LaunchConfiguration("algo").perform(context)
    use_sim_time = _as_bool(LaunchConfiguration("use_sim_time").perform(context))
    config_dir = LaunchConfiguration("config_dir").perform(context)

    if algo not in SUPPORTED_ALGOS:
        raise RuntimeError(
            f"algo '{algo}' is not supported on ROS2 (supported: {', '.join(SUPPORTED_ALGOS)})"
        )

    params_path = os.path.join(config_dir, f"{algo}.yaml")
    with open(params_path) as f:
        params = yaml.safe_load(f) or {}
    if not isinstance(params, dict):
        raise RuntimeError(f"{params_path} must be a flat mapping of parameters")
    params["use_sim_time"] = use_sim_time

    return [
        Node(
            package="slam_toolbox",
            executable="sync_slam_toolbox_node",
            name="slam_toolbox",
            parameters=[params],
            output="screen",
        )
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("algo", default_value="slam_toolbox"),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("config_dir", default_value=_default_config_dir()),
        OpaqueFunction(function=_setup),
    ])
