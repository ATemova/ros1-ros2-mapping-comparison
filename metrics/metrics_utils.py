#!/usr/bin/env python3

import csv
from statistics import median

def read_metrics(filename):
    cpu = []
    mem = []

    try:
        with open(filename, newline="") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                raise ValueError("CSV file is empty or has no header")

            required_columns = {"cpu_percent_total", "memory_mb"}

            if not required_columns.issubset(reader.fieldnames):
                raise ValueError(
                    "CSV file is missing required columns: "
                    "cpu_percent_total and/or memory_mb"
                )

            for row in reader:
                try:
                    cpu.append(float(row["cpu_percent_total"]))
                    mem.append(float(row["memory_mb"]))
                except (KeyError, ValueError):
                    continue
    except FileNotFoundError:
        raise FileNotFoundError(f"CSV file not found: {filename}")
            
    return cpu, mem


def calculate_stats(cpu, mem):
    return {
        "avg_cpu": sum(cpu) / len(cpu),
        "median_cpu": median(cpu),
        "min_cpu": min(cpu),
        "max_cpu": max(cpu),
        
        "avg_memory": sum(mem) / len(mem),
        "median_memory": median(mem),
        "min_memory": min(mem),
        "max_memory": max(mem),
                
        "samples": len(cpu),
    }