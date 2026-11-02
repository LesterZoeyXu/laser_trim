"""激光调阻 1 Ω 段的简化版贝叶斯优化工具

只用 1 Ω 段的数据训练一个 GP，输入为 (频率, 速度)，输出为分数，模型不使用目标阻值。
推荐时频率在 10～100 kHz 内搜索。历史数据只有 10、50、100 kHz，中间的频率是模型插值，把握较低。

用法：
  uv run trim_bo_1ohm.py check                     检查数据，评估模型预测能力
  uv run trim_bo_1ohm.py ask [-n 3]                推荐下一组（或 n 组）实验
  uv run trim_bo_1ohm.py tell 50 13 40 0.9 [-m 备注]  录入实验：频率 速度 良率 FT_SD
  uv run trim_bo_1ohm.py status                    查看已测参数的排名
  uv run trim_bo_1ohm.py undo                      删除最后一条实验记录

新实验记录在 experiments_1ohm.csv 中，与 trim_bo.py 的 experiments.csv 互不影响。
"""
import argparse
import os
import sys
import warnings
from datetime import datetime

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("OMP_NUM_THREADS", "4")

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from scipy.stats import norm
from sklearn.metrics import r2_score
from sklearn.model_selection import KFold

from bayes_optim.surrogate import GaussianProcess, trend

# ============================== 配置 ==============================
HISTORY_FILE = "data/simple_data_1ohm.csv"  # 列：频率、速度、良率、FT SD
EXPERIMENTS_FILE = "experiments_1ohm.csv"
FREQ_RANGE = (10.0, 100.0)  # 推荐时搜索的频率范围(kHz)
FREQ_STEP = 5.0
SPEED_RANGE = (5.0, 15.0)  # 推荐时搜索的速度范围
SPEED_STEP = 0.5
BATCH_MIN_GAP = 2.0  # 一批多组推荐时，频率相近的两组，速度至少相隔多少 mm/s
BATCH_FREQ_GAP = 15.0  # 频率相差不到这么多 kHz，就算频率相近
YIELD_WEIGHT, SD_WEIGHT = 0.5, 1.0  # 分数 = 0.5 × 良率 - 1 × FT SD
SEED = 42
# ==================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
FEATURES = ["freq", "speed"]
LB = np.array([FREQ_RANGE[0], SPEED_RANGE[0]], dtype=float)
UB = np.array([FREQ_RANGE[1], SPEED_RANGE[1]], dtype=float)
EXP_COLUMNS = {"freq": "频率(kHz)", "speed": "速度(mm/s)", "yield": "良率(%)", "sd": "FT SD(%)"}


def path(f):
    return os.path.join(HERE, f)


def score(yield_pct, sd):
    return YIELD_WEIGHT * yield_pct - SD_WEIGHT * sd


def to_unit(X):
    """原始单位 -> [0, 1]"""
    return (np.asarray(X, dtype=float) - LB) / (UB - LB)


def load_experiments():
    if not os.path.exists(path(EXPERIMENTS_FILE)):
        return pd.DataFrame(columns=["时间", *EXP_COLUMNS.values(), "备注"])
    return pd.read_csv(path(EXPERIMENTS_FILE), encoding="utf-8-sig")


def load_data():
    if not os.path.exists(path(HISTORY_FILE)):
        sys.exit(f"错误：找不到数据文件 {path(HISTORY_FILE)}")
    hist = pd.read_csv(path(HISTORY_FILE), encoding="utf-8-sig")
    hist = hist.rename(columns={v: k for k, v in EXP_COLUMNS.items()})[list(EXP_COLUMNS)].astype(float)

    exps = load_experiments().rename(columns={v: k for k, v in EXP_COLUMNS.items()})
    df = pd.concat([hist, exps[list(EXP_COLUMNS)].astype(float)], ignore_index=True)
    df["score"] = score(df["yield"], df.sd)
    return df


class Model:
    """(频率, 速度) -> 分数；对外的预测都是原始分数单位"""

    def __init__(self, X, y):
        self.mu, self.sigma = y.mean(), y.std()
        np.random.seed(SEED)  # gpr.py 的随机重启用全局随机数，random_state 管不到
        self.gp = GaussianProcess(
            mean=trend.constant_trend(2),
            corr="matern",
            thetaL=np.ones(2),
            thetaU=1e3 * np.ones(2),
            nugget=1e-6,
            noise_estim=True,
            optimizer="BFGS",
            wait_iter=10,
            random_start=30,
            likelihood="concentrated",
            eval_budget=2000,
            random_state=SEED,
        )
        self.gp.fit(to_unit(X), (y - self.mu) / self.sigma)

    def predict(self, X):
        mean, mse = self.gp.predict(to_unit(X), eval_MSE=True)
        return np.ravel(mean) * self.sigma + self.mu, np.sqrt(np.maximum(np.ravel(mse), 0)) * self.sigma


def fit(df):
    return Model(df[FEATURES].values, df.score.values)


def tested_points(df, model):
    """做过的参数：实测均值 + 模型预测，按模型预测从高到低排序"""
    t = df.groupby(FEATURES).agg(n=("score", "size"), y=("yield", "mean"), sd=("sd", "mean")).reset_index()
    t["pred"] = model.predict(t[FEATURES].values)[0]
    return t.sort_values("pred", ascending=False, ignore_index=True)


# ================================== 子命令 ==================================


def cmd_check(args):
    df = load_data()
    print(f"1 Ω 段数据 {len(df)} 条，分数范围 {df.score.min():.2f} ~ {df.score.max():.2f}")
    for f, g in df.groupby("freq"):
        print(f"  {f:g} kHz：{len(g)} 条，平均分 {g.score.mean():.1f}")

    X, y = df[FEATURES].values, df.score.values
    pred = np.empty_like(y)
    for train, test in KFold(5, shuffle=True, random_state=SEED).split(X):
        pred[test] = Model(X[train], y[train]).predict(X[test])[0]
    print(f"\n5 折交叉验证：R² = {r2_score(y, pred):.3f}，预测误差 RMSE = {np.sqrt(np.mean((y - pred) ** 2)):.2f} 分")


def cmd_ask(args):
    df = load_data()
    model = fit(df)
    freqs = np.arange(FREQ_RANGE[0], FREQ_RANGE[1] + FREQ_STEP / 2, FREQ_STEP)
    speeds = np.arange(SPEED_RANGE[0], SPEED_RANGE[1] + SPEED_STEP / 2, SPEED_STEP)
    cand = pd.DataFrame([(f, s) for f in freqs for s in speeds], columns=FEATURES).astype(float)
    cand["mean"], cand["std"] = model.predict(cand[FEATURES].values)

    # 实验有噪声，EI 的基准用已测参数的模型预测最高分，而不是实测最高分
    best = tested_points(df, model).pred.iloc[0]
    std = np.maximum(cand["std"], 1e-9)
    z = (cand["mean"] - best) / std
    cand["ei"] = (cand["mean"] - best) * norm.cdf(z) + std * norm.pdf(z)

    picks = []
    for _, row in cand.sort_values("ei", ascending=False).iterrows():
        if all(abs(row.freq - p.freq) >= BATCH_FREQ_GAP or abs(row.speed - p.speed) >= BATCH_MIN_GAP for p in picks):
            picks.append(row)
        if len(picks) == args.n:
            break

    print(f"基于 {len(df)} 条 1 Ω 段数据，当前模型最优分数 ≈ {best:.1f}，推荐实验：")
    for i, p in enumerate(picks, 1):
        print(f"  #{i}: {p.freq:g} kHz，速度 {p.speed:g} mm/s   模型预测分数 ≈ {p['mean']:.1f} ± {p['std']:.1f}")
    print(f"\n做完实验后录入结果：uv run trim_bo_1ohm.py tell {picks[0].freq:g} {picks[0].speed:g} <良率%> <FT_SD>")


def cmd_tell(args):
    if not FREQ_RANGE[0] <= args.freq <= FREQ_RANGE[1]:
        sys.exit(f"错误：频率 {args.freq:g} 超出范围 {FREQ_RANGE[0]:g} ~ {FREQ_RANGE[1]:g} kHz，未录入")
    if not 0 <= args.yield_pct <= 100 or args.sd < 0:
        sys.exit("错误：良率应在 0 ~ 100（%）之间，FT SD 不能为负，未录入")

    exps = load_experiments()
    row = dict(zip(EXP_COLUMNS.values(), (args.freq, args.speed, args.yield_pct, args.sd)))
    row = {"时间": datetime.now().strftime("%Y-%m-%d %H:%M"), **row, "备注": args.m or ""}
    exps = pd.concat([exps, pd.DataFrame([row])], ignore_index=True)
    exps.to_csv(path(EXPERIMENTS_FILE), index=False, encoding="utf-8-sig")
    print(f"已录入第 {len(exps)} 次实验：{args.freq:g} kHz，{args.speed:g} mm/s，分数 {score(args.yield_pct, args.sd):.2f}")


def cmd_status(args):
    df = load_data()
    tested = tested_points(df, fit(df))
    shown = tested.head(args.top).rename(
        columns={"freq": "频率", "speed": "速度", "n": "次数", "y": "良率%", "sd": "FT SD", "pred": "预测分数"}
    )
    print(f"1 Ω 段数据 {len(df)} 条，新实验 {len(load_experiments())} 条，已测参数排名（前 {len(shown)} 组）：")
    print(shown.to_string(index=False, float_format="%.2f"))


def cmd_undo(args):
    exps = load_experiments()
    if not len(exps):
        sys.exit("没有可删除的实验记录")
    last = exps.iloc[-1]
    exps.iloc[:-1].to_csv(path(EXPERIMENTS_FILE), index=False, encoding="utf-8-sig")
    print("已删除最后一条记录：" + ", ".join(f"{k}={v}" for k, v in last.items() if str(v) != "nan"))


def main():
    p = argparse.ArgumentParser(description="激光调阻 1 Ω 段的简化版贝叶斯优化工具")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="检查数据，评估模型能否预测分数").set_defaults(func=cmd_check)
    a = sub.add_parser("ask", help="推荐下一组实验参数")
    a.add_argument("-n", type=int, default=1, help="一次推荐几组参数（默认 1）")
    a.set_defaults(func=cmd_ask)
    t = sub.add_parser("tell", help="录入一次实验结果")
    t.add_argument("freq", type=float, help="实际使用的频率(kHz)")
    t.add_argument("speed", type=float, help="实际使用的速度(mm/s)")
    t.add_argument("yield_pct", type=float, metavar="yield", help="良率(%%)")
    t.add_argument("sd", type=float, help="FT SD(%%)")
    t.add_argument("-m", help="备注")
    t.set_defaults(func=cmd_tell)
    s = sub.add_parser("status", help="查看已测参数的排名")
    s.add_argument("--top", type=int, default=10, help="显示前几组（默认 10）")
    s.set_defaults(func=cmd_status)
    sub.add_parser("undo", help="删除最后一条实验记录").set_defaults(func=cmd_undo)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
