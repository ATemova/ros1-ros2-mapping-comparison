#!/usr/bin/env python3
"""Static checks for the SLAM parameter files, and the parameter-mapping table.

    check_params.py                  validate config/*.yaml
    check_params.py --markdown       print docs/parameter_mapping.md
    check_params.py --check-doc      fail if docs/parameter_mapping.md is out of date

Checks:
  - config/slam_toolbox.yaml is flat, every key is known, and every value has the type
    slam_toolbox declares (ROS2 rejects an int where a double is declared)
  - config/gmapping.yaml values that have a slam_toolbox counterpart are equal to it

Runtime equivalence (what each node actually loaded) is checked separately: every run
writes effective_params.json (experiments/dump_params.py), and compare_groups.py
compares it across ROS1 and ROS2 runs.

Needs PyYAML (present in the ROS images).
"""

import argparse
import os
import sys

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML is required (apt-get install python3-yaml / pip install pyyaml).\n")
    sys.exit(1)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SLAM_TOOLBOX = os.path.join(REPO, "config", "slam_toolbox.yaml")
GMAPPING = os.path.join(REPO, "config", "gmapping.yaml")
DOC = os.path.join(REPO, "docs", "parameter_mapping.md")

# Type slam_toolbox declares for each parameter, and what it controls.
SLAM_TOOLBOX_PARAMS = {
    "mode": ("string", "mapping or localization"),
    "debug_logging": ("bool", "verbose solver logging"),
    "enable_interactive_mode": ("bool", "interactive RViz markers (off: no extra load)"),
    "odom_frame": ("string", "odometry frame"),
    "map_frame": ("string", "map frame"),
    "base_frame": ("string", "robot base frame"),
    "scan_topic": ("string", "LaserScan topic"),
    "solver_plugin": ("string", "pose-graph solver"),
    "ceres_linear_solver": ("string", "Ceres linear solver"),
    "ceres_preconditioner": ("string", "Ceres preconditioner"),
    "ceres_trust_strategy": ("string", "Ceres trust-region strategy"),
    "ceres_dogleg_type": ("string", "Ceres dogleg type"),
    "ceres_loss_function": ("string", "Ceres loss function"),
    "throttle_scans": ("int", "process every Nth scan"),
    "transform_publish_period": ("double", "map->odom publish period [s]"),
    "map_update_interval": ("double", "occupancy grid publish period [s]"),
    "resolution": ("double", "grid cell size [m]"),
    "max_laser_range": ("double", "max range used for the map [m]"),
    "minimum_time_interval": ("double", "min time between processed scans [s]"),
    "transform_timeout": ("double", "TF lookup timeout [s]"),
    "tf_buffer_duration": ("double", "TF buffer length [s]"),
    "stack_size_to_use": ("int", "thread stack size [bytes]"),
    "use_scan_matching": ("bool", "scan matching on/off"),
    "use_scan_barycenter": ("bool", "use scan barycenter for distance"),
    "minimum_travel_distance": ("double", "min travel before a new scan is added [m]"),
    "minimum_travel_heading": ("double", "min rotation before a new scan is added [rad]"),
    "scan_buffer_size": ("int", "scans kept in the local chain"),
    "scan_buffer_maximum_scan_distance": ("double", "max distance in the local chain [m]"),
    "link_match_minimum_response_fine": ("double", "min response to link scans"),
    "link_scan_maximum_distance": ("double", "max distance to link scans [m]"),
    "loop_search_maximum_distance": ("double", "loop closure search radius [m]"),
    "do_loop_closing": ("bool", "loop closure on/off"),
    "loop_match_minimum_chain_size": ("int", "min chain size for a loop closure"),
    "loop_match_maximum_variance_coarse": ("double", "max coarse variance for a loop closure"),
    "loop_match_minimum_response_coarse": ("double", "min coarse response for a loop closure"),
    "loop_match_minimum_response_fine": ("double", "min fine response for a loop closure"),
    "correlation_search_space_dimension": ("double", "scan-match search window [m]"),
    "correlation_search_space_resolution": ("double", "scan-match search resolution [m]"),
    "correlation_search_space_smear_deviation": ("double", "scan-match smear deviation"),
    "loop_search_space_dimension": ("double", "loop search window [m]"),
    "loop_search_space_resolution": ("double", "loop search resolution [m]"),
    "loop_search_space_smear_deviation": ("double", "loop search smear deviation"),
    "distance_variance_penalty": ("double", "distance variance penalty"),
    "angle_variance_penalty": ("double", "angle variance penalty"),
    "fine_search_angle_offset": ("double", "fine angular search range [rad]"),
    "coarse_search_angle_offset": ("double", "coarse angular search range [rad]"),
    "coarse_angle_resolution": ("double", "coarse angular resolution [rad]"),
    "minimum_angle_penalty": ("double", "min angle penalty"),
    "minimum_distance_penalty": ("double", "min distance penalty"),
    "use_response_expansion": ("bool", "expand search when response is low"),
}

# GMapping parameter -> (slam_toolbox counterpart, how they relate)
GMAPPING_TO_SLAM_TOOLBOX = {
    "base_frame": ("base_frame", "same frame"),
    "odom_frame": ("odom_frame", "same frame"),
    "map_frame": ("map_frame", "same frame"),
    "delta": ("resolution", "grid cell size [m]"),
    "maxUrange": ("max_laser_range", "range used for mapping [m]"),
    "map_update_interval": ("map_update_interval", "map publish period [s]"),
    "linearUpdate": ("minimum_travel_distance", "travel before a scan is processed [m]"),
    "angularUpdate": ("minimum_travel_heading", "rotation before a scan is processed [rad]"),
    "transform_publish_period": ("transform_publish_period", "map->odom publish period [s]"),
}

# GMapping parameters with no slam_toolbox counterpart (different algorithm).
GMAPPING_ONLY = {
    "maxRange": "sensor max range; beams beyond it are free space [m]",
    "temporalUpdate": "process a scan after this time even without motion (-1 = off) [s]",
    "particles": "particle count of the Rao-Blackwellized filter",
    "resampleThreshold": "Neff threshold for resampling",
    "minimumScore": "min scan-match score to accept a pose",
    "srr": "odometry error: translation from translation",
    "srt": "odometry error: translation from rotation",
    "str": "odometry error: rotation from translation",
    "stt": "odometry error: rotation from rotation",
    "xmin": "initial map extent [m]",
    "ymin": "initial map extent [m]",
    "xmax": "initial map extent [m]",
    "ymax": "initial map extent [m]",
}

# Keys of the removed v0.1.0 ros1/params/mapping.yaml, which were never loaded and are
# not GMapping parameters.
LEGACY_KEYS = {
    "map_resolution": ("delta", "resolution"),
    "max_range": ("maxUrange", "max_laser_range"),
    "update_rate": ("map_update_interval (period, not rate)", "map_update_interval"),
}


def load(path):
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def type_ok(expected, value):
    if expected == "double":
        return isinstance(value, float)
    if expected == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    return False


def validate(st, gm):
    errors = []
    for key, value in st.items():
        if isinstance(value, (dict, list)):
            errors.append(f"slam_toolbox.yaml: '{key}' is nested; the file must be flat")
            continue
        if key == "use_sim_time":
            errors.append("slam_toolbox.yaml: do not set use_sim_time here; the launch files set it")
            continue
        if key not in SLAM_TOOLBOX_PARAMS:
            errors.append(f"slam_toolbox.yaml: unknown key '{key}' (add it to SLAM_TOOLBOX_PARAMS in {os.path.basename(__file__)})")
            continue
        expected = SLAM_TOOLBOX_PARAMS[key][0]
        if not type_ok(expected, value):
            hint = " (write it with a decimal point, e.g. 5.0)" if expected == "double" and isinstance(value, int) else ""
            errors.append(f"slam_toolbox.yaml: '{key}' must be {expected}, got {type(value).__name__} {value!r}{hint}")

    for key in gm:
        if key not in GMAPPING_TO_SLAM_TOOLBOX and key not in GMAPPING_ONLY:
            errors.append(f"gmapping.yaml: unknown key '{key}' (add it to the tables in {os.path.basename(__file__)})")
    for gkey, (skey, _) in GMAPPING_TO_SLAM_TOOLBOX.items():
        if gkey not in gm:
            errors.append(f"gmapping.yaml: missing '{gkey}' (counterpart of slam_toolbox '{skey}')")
        elif skey not in st:
            errors.append(f"slam_toolbox.yaml: missing '{skey}' (counterpart of gmapping '{gkey}')")
        elif gm[gkey] != st[skey]:
            errors.append(f"gmapping '{gkey}'={gm[gkey]!r} differs from slam_toolbox '{skey}'={st[skey]!r}")
    return errors


def fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return f"`{v}`"


def markdown(st, gm):
    out = [
        "# Parameter mapping",
        "",
        "<!-- Generated by experiments/check_params.py --markdown. Do not edit by hand. -->",
        "",
        "## How equivalence is guaranteed",
        "",
        "1. **One file for both stacks.** `config/slam_toolbox.yaml` is loaded unchanged by "
        "`ros1/launch/mapping.launch` (`rosparam load`) and `ros2/launch/mapping.launch.py` "
        "(passed to the node as a dict). `use_sim_time` is the only parameter the launch files add.",
        "2. **Static check (CI).** `experiments/check_params.py` verifies every key is known, has the type "
        "slam_toolbox declares, and that GMapping values match their slam_toolbox counterparts.",
        "3. **Runtime check (every run).** After the SLAM node starts, the runner dumps the parameters "
        "the node actually holds (`rosparam get` / `ros2 param dump`) into `effective_params.json` "
        "and fails the run if any value differs from the config. "
        "`metrics/compare_groups.py` then confirms the effective values are identical across all ROS1 and ROS2 runs.",
        "",
        "## slam_toolbox (ROS1 Noetic and ROS2 Humble)",
        "",
        "| Parameter | Type | Value | Controls |",
        "|---|---|---|---|",
    ]
    for key, value in st.items():
        t, desc = SLAM_TOOLBOX_PARAMS.get(key, ("?", ""))
        out.append(f"| `{key}` | {t} | {fmt(value)} | {desc} |")
    out += [
        "",
        "Not set here, so each version uses its own default: parameters that exist only in one "
        "version (for example `min_laser_range`, `use_map_saver` on ROS2).",
        "",
        "## GMapping (ROS1 baseline) ↔ slam_toolbox",
        "",
        "| GMapping | Value | slam_toolbox | Value | Meaning |",
        "|---|---|---|---|---|",
    ]
    for gkey, (skey, desc) in GMAPPING_TO_SLAM_TOOLBOX.items():
        out.append(f"| `{gkey}` | {fmt(gm.get(gkey))} | `{skey}` | {fmt(st.get(skey))} | {desc} |")
    out += [
        "",
        "### GMapping-only parameters",
        "",
        "| Parameter | Value | Meaning |",
        "|---|---|---|",
    ]
    for key, desc in GMAPPING_ONLY.items():
        out.append(f"| `{key}` | {fmt(gm.get(key))} | {desc} |")
    out += [
        "",
        "## Removed in v0.2: `ros1/params/mapping.yaml`",
        "",
        "This v0.1.0 file was never loaded by the ROS1 launch file, and its keys are not GMapping parameters.",
        "",
        "| Old key | GMapping parameter | slam_toolbox parameter |",
        "|---|---|---|",
    ]
    for old, (g, s) in LEGACY_KEYS.items():
        out.append(f"| `{old}` | `{g}` | `{s}` |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Validate SLAM parameter files.")
    ap.add_argument("--markdown", action="store_true", help="print the parameter-mapping table")
    ap.add_argument("--check-doc", action="store_true", help="fail if docs/parameter_mapping.md is stale")
    args = ap.parse_args()

    st = load(SLAM_TOOLBOX)
    gm = load(GMAPPING)

    if args.markdown:
        sys.stdout.write(markdown(st, gm))
        return

    errors = validate(st, gm)
    if args.check_doc:
        try:
            current = open(DOC).read()
        except OSError:
            current = ""
        if current != markdown(st, gm):
            errors.append("docs/parameter_mapping.md is out of date: "
                          "python3 experiments/check_params.py --markdown > docs/parameter_mapping.md")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {len(st)} slam_toolbox parameters, {len(GMAPPING_TO_SLAM_TOOLBOX)} aligned GMapping parameters.")


if __name__ == "__main__":
    main()
