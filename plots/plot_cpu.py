import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("results/raw/ros1_cpu_mem.csv")
plt.plot(df["time"], df["cpu_percent"])
plt.xlabel("Time")
plt.ylabel("CPU Usage (%)")
plt.show()