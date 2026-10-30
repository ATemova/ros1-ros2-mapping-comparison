"""ROS2 mapping launch (Humble and Jazzy).

Loads config/slam_toolbox.yaml, the same flat parameter file ROS1 loads, and passes
it to slam_toolbox as a dict, so every stack runs with identical parameters.

From Jazzy on, slam_toolbox nodes are lifecycle nodes: this launch configures and
activates the node itself (autostart), as slam_toolbox's own launch files do. On Humble
it is a plain node.

Launch arguments:
    algo          slam_toolbox (only option on ROS2)
    use_sim_time  true for bag replay
    config_dir    directory holding slam_toolbox.yaml (default: <repo>/config)
"""

import os

import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, OpaqueFunction, RegisterEventHandler
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

SUPPORTED_ALGOS = ("slam_toolbox",)
NON_LIFECYCLE_DISTROS = ("foxy", "galactic", "humble", "iron")


def _default_config_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir, "config"))


def _as_bool(text):
    return str(text).strip().lower() in ("1", "true", "yes", "on")


def _lifecycle_actions(params):
    from launch.events import matches_action
    from launch_ros.actions import LifecycleNode
    from launch_ros.event_handlers import OnStateTransition
    from launch_ros.events.lifecycle import ChangeState
    from lifecycle_msgs.msg import Transition

    params["use_lifecycle_manager"] = False
    node = LifecycleNode(
        package="slam_toolbox",
        executable="sync_slam_toolbox_node",
        name="slam_toolbox",
        namespace="",
        parameters=[params],
        output="screen",
    )
    configure = EmitEvent(event=ChangeState(
        lifecycle_node_matcher=matches_action(node),
        transition_id=Transition.TRANSITION_CONFIGURE,
    ))
    activate = RegisterEventHandler(OnStateTransition(
        target_lifecycle_node=node,
        start_state="configuring",
        goal_state="inactive",
        entities=[EmitEvent(event=ChangeState(
            lifecycle_node_matcher=matches_action(node),
            transition_id=Transition.TRANSITION_ACTIVATE,
        ))],
    ))
    return [node, activate, configure]


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

    distro = os.environ.get("ROS_DISTRO", "humble")
    if distro not in NON_LIFECYCLE_DISTROS:
        return _lifecycle_actions(params)

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
