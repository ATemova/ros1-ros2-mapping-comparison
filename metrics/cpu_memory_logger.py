import psutil
import time
import csv
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
args = parser.parse_args()

with open(args.output, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["time", "cpu_percent", "memory_mb"])

    while True:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().used / (1024 * 1024)
        writer.writerow([time.time(), cpu, mem])