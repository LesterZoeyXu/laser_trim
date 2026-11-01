"""生成一份【模拟】的激光调阻历史数据，仅用于演示工具流程，不代表真实工艺规律。

列名与真实数据一致。假设分数随目标阻值和速度平滑变化，不同配方的最佳速度不同，并带有实验噪声。
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(0)
rows = []
for target in [100, 1e3, 1e4, 1e5, 5e5, 1e6, 5e6, 1e7]:
    for freq, power, pulse, best_speed in [(10, 0.811, 7.2, 6), (50, 3.142, 16.3, 9), (100, 0.966, 26.0, 12)]:
        for speed in [5, 7, 9, 11, 13, 15]:
            for _ in range(3):
                base = 85 - 0.8 * (speed - best_speed) ** 2 - 12 * (np.log10(target) - 4) ** 2 / (1 + freq / 50)
                good = np.clip(base + rng.normal(0, 5), 0, 100)
                rows.append({
                    "电阻修阻目标阻值(Ω)": target,
                    "功率(0w-10w)": power,
                    "修阻速度(1mm/s-20 mm/s)": speed,
                    "频率(1khz-100Khz)": freq,
                    "脉宽(1ns~500ns)": pulse,
                    "良率(%)": round(good, 2),
                    "FT SD(%)": round(max(0.05, 3 - good / 35 + rng.normal(0, 0.2)), 3),
                })
pd.DataFrame(rows).to_csv("demo_history.csv", index=False, encoding="utf-8-sig")
print(f"已生成 demo_history.csv，共 {len(rows)} 条记录")
