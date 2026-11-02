"""从原始 Excel 生成 trim_bo_1ohm.py 用的训练数据 data/simple_data_1ohm.csv

只保留目标阻值在指定范围内的记录，输出 5 列：频率、速度、良率、FT SD、分数。

用法：
  uv run make_simple_data.py                                   默认：1 Ω 段（0.5 ~ 2 Ω）
  uv run make_simple_data.py --min 0.9 --max 1.05 -o data/simple_data_1ohm_only.csv   只要 1 Ω
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER_ROW = 2  # Excel 中列名所在行（从 0 开始数）
COLUMNS = {  # 程序用名 -> Excel 里的列名
    "target": "电阻修阻目标阻值(Ω)",
    "freq": "频率(1khz-100Khz)",
    "speed": "修阻速度(1mm/s-20 mm/s)",
    "yield": "良率(%)",
    "sd": "FT SD(%)",
}
VALID_SPEED = (1.0, 20.0)  # 设备允许的速度，超出的记录视为录入错误
YIELD_WEIGHT, SD_WEIGHT = 0.5, 1.0  # 分数 = 0.5 × 良率 - 1 × FT SD


def main():
    p = argparse.ArgumentParser(description="从原始 Excel 生成简化的训练数据 CSV")
    p.add_argument("-i", "--input", default="data/AI参数优化项目数据统计.xlsx", help="原始 Excel 文件")
    p.add_argument("-o", "--output", default="data/simple_data_1ohm.csv", help="输出的 CSV 文件")
    p.add_argument("--min", type=float, default=0.5, help="目标阻值下限(Ω)，默认 0.5")
    p.add_argument("--max", type=float, default=2.0, help="目标阻值上限(Ω)，默认 2")
    args = p.parse_args()
    src, dst = (os.path.join(HERE, f) for f in (args.input, args.output))

    if not os.path.exists(src):
        sys.exit(f"错误：找不到 {src}")
    df = pd.read_excel(src, header=HEADER_ROW)
    missing = [c for c in COLUMNS.values() if c not in df.columns]
    if missing:
        sys.exit(f"错误：Excel 中找不到列 {missing}，请检查 COLUMNS 配置")

    df = df.rename(columns={v: k for k, v in COLUMNS.items()})[list(COLUMNS)]
    n0 = len(df)
    df = df.apply(pd.to_numeric, errors="coerce").dropna().astype(float)
    n_valid = len(df)
    df = df[df.speed.between(*VALID_SPEED)]
    n_speed = n_valid - len(df)
    df = df[df.target.between(args.min, args.max)]
    if df.empty:
        sys.exit(f"错误：目标阻值在 {args.min:g} ~ {args.max:g} Ω 内没有数据")

    out = pd.DataFrame({
        "频率(kHz)": df.freq.astype(int),
        "速度(mm/s)": df.speed,
        "良率(%)": df["yield"],
        "FT SD(%)": df.sd,
        "分数": YIELD_WEIGHT * df["yield"] - SD_WEIGHT * df.sd,
    })
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    out.to_csv(dst, index=False, encoding="utf-8-sig", float_format="%.4f")

    print(f"读取 {args.input}：{n0} 条，去掉缺失 {n0 - n_valid} 条、速度超出 {VALID_SPEED[0]:g}~{VALID_SPEED[1]:g} 的 {n_speed} 条")
    print(f"目标阻值 {args.min:g} ~ {args.max:g} Ω：{len(out)} 条，包含阻值 {sorted(df.target.unique().tolist())}")
    print(f"已写入 {args.output}")


if __name__ == "__main__":
    main()
