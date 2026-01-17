import pandas as pd
import sys

if len(sys.argv) != 2:
    print("Usage: summarize_metrics.py <cpu_mem.csv>")
    sys.exit(1)

df = pd.read_csv(sys.argv[1])

avg_cpu = df["cpu_percent_total"].mean()
max_cpu = df["cpu_percent_total"].max()
avg_mem = df["memory_mb"].mean()
max_mem = df["memory_mb"].max()

print(
    f"avg_cpu_percent,{avg_cpu:.2f},"
    f"max_cpu_percent,{max_cpu:.2f},"
    f"avg_memory_mb,{avg_mem:.2f},"
    f"max_memory_mb,{max_mem:.2f}"
)