#!/usr/bin/env python3
"""Write run_manifest.json: everything needed to reproduce or audit one run.

Usage: write_manifest.py <run_dir> --params f --launch f [--bag path] [--qos f]

Contents:
  git        commit, branch, dirty (GIT_DIRTY from the host when run in Docker)
  image      Docker image tag and id (IMAGE_TAG / IMAGE_ID from the Makefile or run_matrix.sh)
  inputs     sha256 of the parameter file, launch file, QoS overrides and the bag
             (bag hashes are cached next to the bag as <bag>.sha256.json)
  software   ROS distribution, RMW, versions of the ROS packages that matter, Python libs
  host       CPU model and count, memory, kernel, OS, applied CPU/memory limits
  env        ROS / DDS / Zenoh environment variables that change behaviour
Standard library only.
"""

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from write_meta import cpu_model, git_info, mem_total_mb, resource_limits  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
ENV_KEYS = (
    "ROS_DISTRO", "RMW_IMPLEMENTATION", "ROS_DOMAIN_ID", "ROS_LOCALHOST_ONLY",
    "ROS_AUTOMATIC_DISCOVERY_RANGE", "ROS_STATIC_PEERS", "CYCLONEDDS_URI",
    "FASTRTPS_DEFAULT_PROFILES_FILE", "FASTDDS_DEFAULT_PROFILES_FILE", "RMW_FASTRTPS_USE_QOS_FROM_XML",
    "ZENOH_ROUTER_CONFIG_URI", "ZENOH_SESSION_CONFIG_URI", "ZENOH_CONFIG_OVERRIDE",
    "ROS_MASTER_URI", "ROS_IP", "ROS_HOSTNAME", "CPU_SET", "CONDITION",
)
ROS_PACKAGES = (
    "slam-toolbox", "slam-gmapping", "gmapping", "map-server", "nav2-map-server",
    "roscpp", "rospy", "rosbag", "rclcpp", "rclpy", "rosbag2", "rosbag2-storage-default-plugins",
    "rmw-fastrtps-cpp", "rmw-cyclonedds-cpp", "rmw-zenoh-cpp", "fastrtps", "fastdds", "cyclonedds",
    "zenoh-cpp-vendor", "tf2-ros",
)


def sha256_file(path, h=None):
    h = h or hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h


def sha256_path(path):
    """sha256 of a file, or of all files in a directory (relative names + contents, sorted)."""
    if os.path.isfile(path):
        return sha256_file(path).hexdigest(), os.path.getsize(path)
    h = hashlib.sha256()
    size = 0
    for root, _, files in sorted(os.walk(path)):
        for name in sorted(files):
            full = os.path.join(root, name)
            h.update(os.path.relpath(full, path).encode())
            sha256_file(full, h)
            size += os.path.getsize(full)
    return h.hexdigest(), size


def bag_hash(path):
    path = path.rstrip("/")
    stat_src = path if os.path.isfile(path) else os.path.join(path, "metadata.yaml")
    st = os.stat(stat_src)
    key = {"size": os.path.getsize(path) if os.path.isfile(path) else None, "mtime": st.st_mtime}
    cache = f"{path}.sha256.json"
    try:
        with open(cache) as f:
            c = json.load(f)
        if c.get("key") == key:
            return c["sha256"], c["size_bytes"]
    except (OSError, ValueError, KeyError):
        pass
    digest, size = sha256_path(path)
    try:
        with open(cache, "w") as f:
            json.dump({"key": key, "sha256": digest, "size_bytes": size}, f)
    except OSError:
        pass
    return digest, size


def git_dirty():
    env = os.environ.get("GIT_DIRTY")
    if env in ("true", "false"):
        return env == "true"
    try:
        out = subprocess.run(["git", "-C", REPO, "status", "--porcelain", "--untracked-files=no"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def ros_package_versions(distro):
    if not distro:
        return {}
    names = [f"ros-{distro}-{p}" for p in ROS_PACKAGES]
    try:
        out = subprocess.run(["dpkg-query", "-W", "-f=${Package} ${Version}\\n"] + names,
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return {}
    versions = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1]:
            versions[parts[0].replace(f"ros-{distro}-", "")] = parts[1]
    return versions


def python_versions():
    out = {"python": platform.python_version()}
    for mod in ("numpy", "psutil", "yaml", "matplotlib", "rosbags"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "installed")
        except Exception:  # noqa: BLE001
            pass
    return out


def os_release():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def main():
    ap = argparse.ArgumentParser(description="Write run_manifest.json")
    ap.add_argument("run_dir")
    ap.add_argument("--params", required=True)
    ap.add_argument("--launch", required=True)
    ap.add_argument("--bag")
    ap.add_argument("--qos")
    args = ap.parse_args()

    meta = {}
    try:
        with open(os.path.join(args.run_dir, "run_meta.json")) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        pass

    inputs = {}
    for label, path in (("params", args.params), ("launch", args.launch), ("qos_overrides", args.qos)):
        if path and os.path.exists(path):
            inputs[label] = {"path": os.path.relpath(path, REPO), "sha256": sha256_file(path).hexdigest()}
    combined = hashlib.sha256()
    for label in sorted(inputs):
        combined.update(inputs[label]["sha256"].encode())
    inputs["config_sha256"] = combined.hexdigest()
    if args.bag and os.path.exists(args.bag):
        digest, size = bag_hash(args.bag)
        inputs["bag"] = {"path": args.bag, "sha256": digest, "size_bytes": size}

    distro = os.environ.get("ROS_DISTRO", meta.get("ros_distro"))
    git = git_info(REPO)
    git["dirty"] = git_dirty()
    manifest = {
        "schema_version": 1,
        "experiment_id": meta.get("experiment_id"),
        "variant": meta.get("variant"),
        "condition": meta.get("condition"),
        "git": git,
        "image": {
            "tag": os.environ.get("IMAGE_TAG"),
            "id": os.environ.get("IMAGE_ID"),
            "in_container": os.path.exists("/.dockerenv"),
        },
        "inputs": inputs,
        "software": {
            "ros_distro": distro,
            "rmw": meta.get("rmw"),
            "ros_packages": ros_package_versions(distro),
            "python": python_versions(),
        },
        "host": {
            "hostname": socket.gethostname(),
            "os": os_release(),
            "kernel": platform.release(),
            "arch": platform.machine(),
            "cpu_model": cpu_model(),
            "mem_total_mb": mem_total_mb(),
            "limits": resource_limits(),
        },
        "env": {k: os.environ[k] for k in ENV_KEYS if os.environ.get(k)},
    }
    with open(os.path.join(args.run_dir, "run_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
