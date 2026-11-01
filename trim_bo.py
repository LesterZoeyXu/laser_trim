"""激光调阻工艺的贝叶斯优化 —— 命令行工具

对给定的目标阻值，在 3 个固定配方（频率/功率/脉宽）和修阻速度中推荐下一组实验。

用法：
  uv run trim_bo.py check                            检查数据，评估模型预测能力
  uv run trim_bo.py ask 1e6 [-n 3]                   推荐目标阻值 1 MΩ 的下一组（或 n 组）实验
  uv run trim_bo.py tell 1e6 50 9 92.5 0.4 [-m 备注]  录入实验：目标阻值 频率 速度 良率 FT_SD
  uv run trim_bo.py status [1e6]                     查看所有（或某个）目标阻值的最优参数
  uv run trim_bo.py undo                             删除最后一条实验记录（录错时用）

加 --history 文件 可以换数据来源，例如 uv run trim_bo.py --history demo_history.csv check

模型：每个配方一个高斯过程，输入为 (log10 目标阻值, 速度)，输出为分数。
所有新实验记录在 experiments.csv 中，每次运行都用"历史数据 + 新实验"重新训练，不保存模型状态。
"""
import argparse
import os
import sys
import warnings
from datetime import datetime

# 训练用的矩阵不大，线程开太多只会空转；必须在导入 numpy 之前设置
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("OMP_NUM_THREADS", "4")

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from scipy.stats import norm
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold, KFold

from bayes_optim.surrogate import GaussianProcess, trend

# ======================= 配置：换数据或调整工艺时只需改这里 =======================
HISTORY_FILE = "data/AI参数优化项目数据统计.xlsx"
HEADER_ROW = 2  # Excel 中列名所在行（从 0 开始数）；CSV 的列名固定在第一行
EXPERIMENTS_FILE = "experiments.csv"  # 新实验记录（由 tell 自动维护）
COLUMNS = {  # 程序用名 -> 历史数据里的列名
    "target": "电阻修阻目标阻值(Ω)",
    "freq": "频率(1khz-100Khz)",
    "speed": "修阻速度(1mm/s-20 mm/s)",
    "yield": "良率(%)",
    "sd": "FT SD(%)",
}
RECIPES = {  # 频率(kHz) -> 固定搭配的功率和脉宽
    10: {"功率(W)": 0.811, "脉宽(ns)": 7.2},
    50: {"功率(W)": 3.142, "脉宽(ns)": 16.3},
    100: {"功率(W)": 0.966, "脉宽(ns)": 26.0},
}
VALID_SPEED = (1.0, 20.0)  # 设备允许的速度，超出的历史记录不参与训练
SEARCH_SPEED = (5.0, 15.0)  # 推荐时搜索的速度范围，应设为工艺上稳定、数据较多的区间
SPEED_STEP = 0.5  # 推荐速度的步长（mm/s）
BATCH_MIN_GAP = 2.0  # 一批多组推荐时，同一配方的速度至少相隔多少 mm/s
YIELD_WEIGHT, SD_WEIGHT = 0.5, 1.0  # 分数 = 0.5 × 良率 - 1 × FT SD
SEED = 42
# ===============================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
FEATURES = ["log_target", "speed"]
SPEED_GRID = np.arange(SEARCH_SPEED[0], SEARCH_SPEED[1] + SPEED_STEP / 2, SPEED_STEP)
EXP_COLUMNS = {
    "target": "目标阻值(Ω)",
    "freq": "频率(kHz)",
    "speed": "速度(mm/s)",
    "yield": "良率(%)",
    "sd": "FT SD(%)",
}


def path(f):
    return f if os.path.isabs(f) else os.path.join(HERE, f)


def score(yield_pct, sd):
    return YIELD_WEIGHT * yield_pct - SD_WEIGHT * sd


def fmt_ohm(r):
    for scale, unit in ((1e6, "MΩ"), (1e3, "kΩ")):
        if r >= scale:
            return f"{r / scale:g} {unit}"
    return f"{r:g} Ω"


def fmt_recipe(f):
    return f"{f:g} kHz（" + "，".join(f"{k}={v:g}" for k, v in RECIPES[int(f)].items()) + "）"


def read_table(f):
    f = path(f)
    if not os.path.exists(f):
        sys.exit(f"错误：找不到数据文件 {f}\n试用演示数据：uv run trim_bo.py --history demo_history.csv check")
    if f.endswith((".xlsx", ".xls")):
        return pd.read_excel(f, header=HEADER_ROW)
    try:
        return pd.read_csv(f, encoding="utf-8-sig")
    except UnicodeDecodeError:  # 中文 Windows 下 Excel 另存的 CSV 常为 GBK 编码
        return pd.read_csv(f, encoding="gbk")


def clean(df, columns, source, verbose):
    missing = [c for c in columns.values() if c not in df.columns]
    if missing:
        sys.exit(f"错误：{source} 中找不到列 {missing}，请检查 COLUMNS 配置")
    df = df.rename(columns={v: k for k, v in columns.items()})[list(columns)]
    n0 = len(df)
    df = df.apply(pd.to_numeric, errors="coerce").dropna().astype(float)
    if verbose and n0 > len(df):
        print(f"  {source}：去掉 {n0 - len(df)} 条缺失或非数字的记录")
    ok = df.freq.isin(RECIPES) & df.speed.between(*VALID_SPEED)
    if verbose and not ok.all():
        print(f"  {source}：去掉 {(~ok).sum()} 条配方未知或速度超出 {VALID_SPEED[0]:g}~{VALID_SPEED[1]:g} 的记录")
    return df[ok]


def load_experiments():
    if not os.path.exists(path(EXPERIMENTS_FILE)):
        return pd.DataFrame(columns=["时间", *EXP_COLUMNS.values(), "备注"])
    return pd.read_csv(path(EXPERIMENTS_FILE), encoding="utf-8-sig")


def load_all(args, verbose=False):
    hist = clean(read_table(args.history), COLUMNS, args.history, verbose)
    exps = load_experiments()
    exps = clean(exps, EXP_COLUMNS, EXPERIMENTS_FILE, verbose) if len(exps) else hist.iloc[:0]
    df = pd.concat([hist.assign(new=False), exps.assign(new=True)], ignore_index=True)
    df["score"] = score(df["yield"], df.sd)
    df["log_target"] = np.log10(df.target)
    return df


def feature_scaler(df):
    """输入归一化到 [0, 1]；分别按配方训练时共用同一尺度"""
    lb = np.array([df.log_target.min(), VALID_SPEED[0]])
    ub = np.array([df.log_target.max(), VALID_SPEED[1]])
    return lambda X: (np.asarray(X, dtype=float) - lb) / (ub - lb)


def make_model(dim):
    # theta 下限为 1：长度尺度不超过整个归一化范围。下限太小时，分数平坦的配方会收敛到
    # "theta 极小、方差极大"的退化解，不确定度虚高，EI 就会被带偏
    np.random.seed(SEED)  # gpr.py 的随机重启用全局随机数，random_state 管不到
    return GaussianProcess(
        mean=trend.constant_trend(dim),
        corr="matern",
        thetaL=np.ones(dim),
        thetaU=1e3 * np.ones(dim),
        nugget=1e-6,
        noise_estim=True,  # 实验有噪声：让 GP 自己估计噪声大小
        optimizer="BFGS",
        wait_iter=10,
        random_start=15 * dim,
        likelihood="concentrated",
        eval_budget=1000 * dim,  # 各次重启共用这个预算，太小会跑不满 random_start
        random_state=SEED,
    )


class Models:
    """每个配方一个 GP；对外的预测都是原始分数单位"""

    def __init__(self, df):
        self.scale = feature_scaler(df)
        self.fitted = {}
        for f, g in df.groupby("freq"):
            y = g.score.values
            model = make_model(len(FEATURES))
            model.fit(self.scale(g[FEATURES].values), (y - y.mean()) / y.std())
            self.fitted[f] = (model, y.mean(), y.std())

    def predict(self, f, target, speeds):
        speeds = np.atleast_1d(np.asarray(speeds, dtype=float))
        X = np.column_stack([np.full(len(speeds), np.log10(target)), speeds])
        model, mu, sigma = self.fitted[f]
        mean, mse = model.predict(self.scale(X), eval_MSE=True)
        return np.ravel(mean) * sigma + mu, np.sqrt(np.maximum(np.ravel(mse), 0)) * sigma


def candidates(models, target):
    """目标阻值下，所有配方 × 速度网格的预测"""
    rows = [
        pd.DataFrame(dict(zip(("freq", "speed", "mean", "sd"), (f, SPEED_GRID, *models.predict(f, target, SPEED_GRID)))))
        for f in models.fitted
    ]
    return pd.concat(rows, ignore_index=True)


def tested_points(df, models, target):
    """目标阻值下做过的参数：实测均值 + 模型预测（已按模型预测从高到低排序）"""
    g = df[df.target == target]
    t = g.groupby(["freq", "speed"]).agg(n=("score", "size"), y=("yield", "mean"), sd=("sd", "mean")).reset_index()
    t["mean"] = [models.predict(f, target, s)[0][0] for f, s in zip(t.freq, t.speed)]
    return t.sort_values("mean", ascending=False, ignore_index=True)


def best_so_far(df, models, target, cand):
    """EI 的基准。实验有噪声，实测最高分往往偏高，因此用模型预测值"""
    tested = tested_points(df, models, target)
    return tested["mean"].iloc[0] if len(tested) else cand["mean"].max()


def expected_improvement(mean, sd, best):
    sd = np.maximum(sd, 1e-9)
    z = (mean - best) / sd
    return (mean - best) * norm.cdf(z) + sd * norm.pdf(z)


def pick_batch(cand, n):
    """按 EI 从高到低选，同一配方的速度保持间隔，避免一批实验都挤在一起"""
    picks = []
    for _, row in cand.sort_values("ei", ascending=False).iterrows():
        if all(row.freq != p.freq or abs(row.speed - p.speed) >= BATCH_MIN_GAP for p in picks):
            picks.append(row)
        if len(picks) == n:
            break
    return picks


def require_known_range(df, target):
    if not df.target.min() <= target <= df.target.max():
        sys.exit(f"错误：目标阻值 {fmt_ohm(target)} 超出数据范围 {fmt_ohm(df.target.min())} ~ {fmt_ohm(df.target.max())}")
    if not (df.target == target).any():
        print(f"⚠️ {fmt_ohm(target)} 没有做过实验，以下结果来自相邻阻值的插值，把握较低\n")


def cross_validate(df, splitter, groups=None):
    pred = pd.Series(index=df.index, dtype=float)
    for f, g in df.groupby("freq"):
        X, y = feature_scaler(df)(g[FEATURES].values), g.score.values
        for train, test in splitter.split(X, groups=None if groups is None else g[groups]):
            model = make_model(X.shape[1])
            m, s = y[train].mean(), y[train].std()
            model.fit(X[train], (y[train] - m) / s)
            pred.loc[g.index[test]] = np.ravel(model.predict(X[test])) * s + m
    return r2_score(df.score, pred), np.sqrt(((df.score - pred) ** 2).mean())


# ================================== 子命令 ==================================


def cmd_check(args):
    print("读取数据：")
    df = load_all(args, verbose=True)
    print(f"  可用数据 {len(df)} 条（历史 {(~df.new).sum()} 条，新实验 {df.new.sum()} 条），目标阻值 {df.target.nunique()} 种")
    print(f"  分数 = {YIELD_WEIGHT:g} × 良率 - {SD_WEIGHT:g} × FT SD，范围 {df.score.min():.2f} ~ {df.score.max():.2f}")
    for f, g in df.groupby("freq"):
        print(f"  配方 {fmt_recipe(f)}：{len(g)} 条，平均分 {g.score.mean():.1f}")

    print("\n5 折交叉验证：")
    r2, rmse = cross_validate(df, KFold(5, shuffle=True, random_state=SEED))
    print(f"  已做过的目标阻值：R² = {r2:.3f}，预测误差 RMSE = {rmse:.2f} 分")
    r2_new, rmse_new = cross_validate(df, GroupKFold(5), groups="target")
    print(f"  没做过的目标阻值：R² = {r2_new:.3f}，预测误差 RMSE = {rmse_new:.2f} 分")
    if r2 < 0.3:
        print("⚠️ R² 偏低：工艺参数对分数的解释力有限（或噪声很大），建议先排查数据再做优化")
    else:
        print("模型能较好地预测分数，可以开始优化")


def cmd_ask(args):
    df = load_all(args)
    require_known_range(df, args.target)
    models = Models(df)
    cand = candidates(models, args.target)
    best = best_so_far(df, models, args.target, cand)
    cand["ei"] = expected_improvement(cand["mean"], cand["sd"], best)

    print(f"目标阻值 {fmt_ohm(args.target)}，基于 {len(df)} 条数据，当前模型最优分数 ≈ {best:.1f}，推荐实验：")
    picks = pick_batch(cand, args.n)
    for i, p in enumerate(picks, 1):
        print(f"  #{i}: {fmt_recipe(p.freq)}，速度 {p.speed:g} mm/s   模型预测分数 ≈ {p['mean']:.1f} ± {p['sd']:.1f}")
    print(f"\n做完实验后录入结果：uv run trim_bo.py tell {args.target:.10g} {picks[0].freq:g} {picks[0].speed:g} <良率%> <FT_SD>")
    print("（如果机台上实际设置的参数与推荐值不同，请录入实际值）")


def cmd_tell(args):
    if args.freq not in RECIPES:
        sys.exit(f"错误：频率只能是 {list(RECIPES)} kHz，未录入")
    if not VALID_SPEED[0] <= args.speed <= VALID_SPEED[1]:
        sys.exit(f"错误：速度 {args.speed:g} 超出允许范围 {VALID_SPEED[0]:g} ~ {VALID_SPEED[1]:g}，未录入")
    if not 0 <= args.yield_pct <= 100:
        sys.exit("错误：良率应在 0 ~ 100（%）之间，未录入")
    if not (args.target > 0 and args.sd >= 0):
        sys.exit("错误：目标阻值必须大于 0，FT SD 不能为负，未录入")

    df = load_all(args)
    mean, sd = Models(df).predict(args.freq, args.target, args.speed)  # 录入前的预测，用来观察模型是否靠谱
    s = score(args.yield_pct, args.sd)

    exps = load_experiments()
    row = dict(zip(EXP_COLUMNS.values(), (args.target, args.freq, args.speed, args.yield_pct, args.sd)))
    row = {"时间": datetime.now().strftime("%Y-%m-%d %H:%M"), **row, "备注": args.m or ""}
    exps = pd.concat([exps, pd.DataFrame([row])], ignore_index=True)
    exps.to_csv(path(EXPERIMENTS_FILE), index=False, encoding="utf-8-sig")

    print(f"已录入第 {len(exps)} 次实验：{fmt_ohm(args.target)}，{args.freq:g} kHz，{args.speed:g} mm/s，分数 {s:.2f}")
    print(f"  录入前模型预测 {mean[0]:.1f} ± {sd[0]:.1f}，实测比预测{'高' if s > mean[0] else '低'} {abs(s - mean[0]):.1f} 分")


def cmd_status(args):
    df = load_all(args)
    models = Models(df)
    print(f"历史数据 {(~df.new).sum()} 条，新实验 {df.new.sum()} 条")
    exps = load_experiments()
    if len(exps):
        print("\n新实验记录：")
        print(exps.fillna("").to_string(index=True))

    if args.target is not None:
        require_known_range(df, args.target)
        cand = candidates(models, args.target)
        best = cand.loc[cand.groupby("freq")["mean"].idxmax()]
        print(f"\n{fmt_ohm(args.target)} 各配方的模型最优速度：")
        for _, b in best.sort_values("mean", ascending=False).iterrows():
            print(f"  {fmt_recipe(b.freq)}，速度 {b.speed:g} mm/s   预测分数 {b['mean']:.1f} ± {b['sd']:.1f}")
        tested = tested_points(df, models, args.target)
        if len(tested):
            print("\n已测参数（按模型预测排序，前 5 组）：")
            shown = tested.head(5).rename(columns={"freq": "频率", "speed": "速度", "n": "次数", "y": "良率%", "sd": "FT SD", "mean": "预测分数"})
            print(shown.to_string(index=False, float_format="%.2f"))
        return

    print("\n各目标阻值的推荐参数（模型预测最高的已测参数；良率、SD 为该参数的实测均值）：")
    print(f"  {'目标阻值':<12}{'频率':>9}{'速度':>11}{'预测分数':>10}{'良率%':>9}{'FT SD':>8}{'次数':>6}")
    for target in sorted(df.target.unique()):
        b = tested_points(df, models, target).iloc[0]
        print(f"  {fmt_ohm(target):<14}{b.freq:>6g} kHz{b.speed:>6g} mm/s{b['mean']:>12.1f}{b.y:>10.1f}{b.sd:>9.2f}{b.n:>7.0f}")


def cmd_undo(args):
    exps = load_experiments()
    if not len(exps):
        sys.exit("没有可删除的实验记录")
    last = exps.iloc[-1]
    exps.iloc[:-1].to_csv(path(EXPERIMENTS_FILE), index=False, encoding="utf-8-sig")
    print("已删除最后一条记录：" + ", ".join(f"{k}={v}" for k, v in last.items() if str(v) != "nan"))


def main():
    p = argparse.ArgumentParser(description="激光调阻工艺的贝叶斯优化工具")
    p.add_argument("--history", default=HISTORY_FILE, help="历史数据文件（默认读配置里的 HISTORY_FILE）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="检查数据，评估模型能否预测分数").set_defaults(func=cmd_check)
    a = sub.add_parser("ask", help="推荐下一组实验参数")
    a.add_argument("target", type=float, help="目标阻值(Ω)，可写成 1e6")
    a.add_argument("-n", type=int, default=1, help="一次推荐几组参数（默认 1）")
    a.set_defaults(func=cmd_ask)
    t = sub.add_parser("tell", help="录入一次实验结果")
    t.add_argument("target", type=float, help="目标阻值(Ω)")
    t.add_argument("freq", type=int, help=f"配方频率(kHz)，可选 {list(RECIPES)}")
    t.add_argument("speed", type=float, help="实际使用的速度(mm/s)")
    t.add_argument("yield_pct", type=float, metavar="yield", help="良率(%%)，例如 92.5")
    t.add_argument("sd", type=float, help="FT SD(%%)")
    t.add_argument("-m", help="备注，例如批次号、异常情况")
    t.set_defaults(func=cmd_tell)
    s = sub.add_parser("status", help="查看进度和当前最优参数")
    s.add_argument("target", type=float, nargs="?", help="只看某个目标阻值(Ω)")
    s.set_defaults(func=cmd_status)
    sub.add_parser("undo", help="删除最后一条实验记录").set_defaults(func=cmd_undo)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
