"""生成一份【模拟】的激光调阻历史数据，仅用于演示热启动流程，不代表真实工艺规律。

假设：分数在 频率≈65 kHz、速度≈110 mm/s 附近最高，并带有实验噪声；
历史数据大多集中在常用参数附近，频率记录为整数（用来演示类型转换）。
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(0)
n = 60

freq = np.clip(np.round(rng.normal(55, 8, n)), 20, 100)  # 整数 kHz
speed = np.clip(rng.normal(90, 25, n), 10, 200).round(1)  # mm/s
score = (
    90
    - 0.015 * (freq - 65) ** 2
    - 0.002 * (speed - 110) ** 2
    - 0.0015 * (freq - 65) * (speed - 110)
    + rng.normal(0, 1.5, n)  # 实验噪声
)

# 加入几条重复参数的记录（同一参数做了两次），以及一条缺失分数的记录
dup = pd.DataFrame({"频率": freq[:3], "速度": speed[:3], "分数": score[:3] + rng.normal(0, 1.5, 3)})
df = pd.DataFrame({"频率": freq.astype(int), "速度": speed, "分数": score.round(2)})
df = pd.concat([df, dup.round(2), pd.DataFrame({"频率": [70], "速度": [100.0], "分数": [np.nan]})])
df.to_csv("demo_history.csv", index=False)
print(f"已生成 demo_history.csv，共 {len(df)} 条记录")
