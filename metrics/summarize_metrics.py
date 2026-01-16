import pandas as pd
import sys

df = pd.read_csv(sys.argv[1])

summary = {
    "avg_cpu": df["cpu_percent"].mean(),
    "max_cpu": df["cpu_percent"].max(),
    "avg_mem": df["memory_mb"].mean(),
    "max_mem": df["memory_mb"].max()
}

print(summary)