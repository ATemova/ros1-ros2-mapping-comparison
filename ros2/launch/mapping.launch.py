"""ROS2 mapping launch.

Resolves the params file relative to this launch file so it works whether the
file is launched by path (`ros2 launch <path>/mapping.launch.py`) or from an
installed ament package. If slam_toolbox is not installed, the launch still
succeeds and simply logs a notice, so the experiment pipeline can be smoke
tested without SLAM packages present.
"""

import os

from launch import LaunchDescription
from launch.actions import LogInfo
from launch_ros.actions import Node


def _params_file():
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.abspath(os.path.join(here, os.pardir, "params", "mapping.yaml"))
    if os.path.exists(local):
        return local
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(
            get_package_share_directory("ros2"), "params", "mapping.yaml"
        )
    except Exception:
        return local


def _package_available(name):
    try:
        from ament_index_python.packages import get_package_share_directory
        get_package_share_directory(name)
        return True
    except Exception:
        return False


def generate_launch_description():
    params_file = _params_file()

    if _package_available("slam_toolbox"):
        action = Node(
            package="slam_toolbox",
            executable="sync_slam_toolbox_node",
            name="slam_toolbox",
            parameters=[params_file],
            output="screen",
        )
    else:
        action = LogInfo(
            msg=(
                "[mapping.launch.py] slam_toolbox not found; launching without a "
                "SLAM node. Install 'ros-humble-slam-toolbox' for real mapping."
            )
        )

    return LaunchDescription([action])
