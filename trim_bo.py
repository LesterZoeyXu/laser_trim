"""激光调阻参数的贝叶斯优化 —— 命令行工具

用法：
  python trim_bo.py check                       检查历史数据，评估模型能否预测分数
  python trim_bo.py ask [-n 3]                  推荐下一组（或 n 组）实验参数
  python trim_bo.py tell 63.3 200 74.5 [-m 备注]  录入一次实验：频率 速度 分数
  python trim_bo.py status                      查看实验进度和当前最优参数
  python trim_bo.py undo                        删除最后一条实验记录（录错时用）

所有新实验记录在 experiments.csv 中（可以用 Excel 打开和修改）。
每次 ask/status 都会用"历史数据 + 新实验记录"重新热启动 BO，因此不需要保存优化器状态。
"""
import argparse
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from sklearn.metrics import r2_score
from sklearn.model_selection import KFold

from bayes_optim import BO, NoisyBO, RealSpace
from bayes_optim.surrogate import GaussianProcess, trend

# ======================= 配置：换成你的真实数据时只需改这里 =======================
HISTORY_FILE = "demo_history.csv"  # 历史数据，也可以是 .xlsx
EXPERIMENTS_FILE = "experiments.csv"  # 新实验记录（由 tell 自动维护）
COLUMNS = {"freq": "频率", "speed": "速度", "score": "分数"}  # 程序用名 -> 文件里的列名
UNITS = {"freq": "kHz", "speed": "mm/s"}
BOUNDS = {"freq": (20.0, 100.0), "speed": (10.0, 200.0)}  # 允许搜索的参数范围
MAX_NEW_EXPERIMENTS = 20  # 计划再做多少次实验（历史数据不计入）
SEED = 42
# ===============================================================================

VARS = list(BOUNDS)
LB = np.array([BOUNDS[v][0] for v in VARS])
UB = np.array([BOUNDS[v][1] for v in VARS])
HERE = os.path.dirname(os.path.abspath(__file__))


def name(v):
    return f"{COLUMNS[v]}({UNITS[v]})"


def fmt_params(x):
    return ", ".join(f"{COLUMNS[v]}={x[i]:.1f} {UNITS[v]}" for i, v in enumerate(VARS))


def to_unit(X):
    """原始单位 -> [0, 1]"""
    return (np.asarray(X, dtype=float) - LB) / (UB - LB)


def from_unit(U):
    """[0, 1] -> 原始单位"""
    return np.asarray(U, dtype=float) * (UB - LB) + LB


def path(f):
    return f if os.path.isabs(f) else os.path.join(HERE, f)


def read_table(f):
    f = path(f)
    if f.endswith((".xlsx", ".xls")):
        return pd.read_excel(f)
    try:
        return pd.read_csv(f, encoding="utf-8-sig")
    except UnicodeDecodeError:  # 中文 Windows 下 Excel 另存的 CSV 常为 GBK 编码
        return pd.read_csv(f, encoding="gbk")


def clean(df, source, verbose):
    df = df.rename(columns={v: k for k, v in COLUMNS.items()})
    missing = [COLUMNS[c] for c in VARS + ["score"] if c not in df.columns]
    if missing:
        sys.exit(f"错误：{source} 中找不到列 {missing}，请检查 COLUMNS 配置")
    df = df[VARS + ["score"]]
    n0 = len(df)
    df = df.apply(pd.to_numeric, errors="coerce").dropna()  # 整数 -> 浮点，非数字/空值丢弃
    if verbose and n0 > len(df):
        print(f"  {source}：去掉 {n0 - len(df)} 条缺失或非数字的记录")
    in_range = np.all((df[VARS].values >= LB) & (df[VARS].values <= UB), axis=1)
    if verbose and not in_range.all():
        print(f"  {source}：去掉 {(~in_range).sum()} 条超出搜索范围的记录")
    return df[in_range]


def load_experiments():
    if not os.path.exists(path(EXPERIMENTS_FILE)):
        return pd.DataFrame(columns=["时间", *[COLUMNS[c] for c in VARS + ["score"]], "备注"])
    return read_table(EXPERIMENTS_FILE)


def load_all(verbose=False):
    """返回 (X, y, 每条数据是否为新实验)"""
    hist = clean(read_table(HISTORY_FILE), HISTORY_FILE, verbose)
    exps = load_experiments()
    exps = clean(exps, EXPERIMENTS_FILE, verbose) if len(exps) else hist.iloc[:0]
    df = pd.concat([hist, exps], ignore_index=True)
    is_new = np.r_[np.zeros(len(hist), bool), np.ones(len(exps), bool)]
    return df[VARS].values.astype(float), df["score"].values.astype(float), is_new


def make_model(dim):
    # 输入已归一化到 [0, 1]，因此 theta 的范围不再需要按量纲缩放
    return GaussianProcess(
        mean=trend.constant_trend(dim),
        corr="matern",
        thetaL=1e-3 * np.ones(dim),
        thetaU=1e3 * np.ones(dim),
        nugget=1e-6,
        noise_estim=True,  # 实验有噪声：让 GP 自己估计噪声大小
        optimizer="BFGS",
        wait_iter=3,
        random_start=10 * len(VARS),
        likelihood="concentrated",
        eval_budget=200 * dim,
        random_state=SEED,
    )


def build_optimizer(X, y, n_point=1):
    """用全部已有数据热启动 BO"""
    np.random.seed(SEED + len(y))  # 数据不变时推荐结果可复现
    space = RealSpace([[0.0, 1.0]] * len(VARS), var_name=VARS)
    return (BO if n_point == 1 else NoisyBO)(
        search_space=space,
        obj_fun=None,  # 实验在机台上做，通过 ask/tell 交互
        model=make_model(len(VARS)),
        warm_data=(to_unit(X).tolist(), y.tolist()),
        n_point=n_point,
        max_FEs=MAX_NEW_EXPERIMENTS,
        minimize=False,  # 分数越高越好
        acquisition_fun="EI" if n_point == 1 else "MGFI",
        random_seed=SEED,
    )


def predict(opt, y, X):
    """模型预测（原始分数单位）：模型在标准化后的分数上训练，需换算回来"""
    mean, mse = opt.model.predict(to_unit(np.atleast_2d(X)), eval_MSE=True)
    return np.ravel(mean) * y.std() + y.mean(), np.sqrt(np.ravel(mse)) * y.std()


def model_best(opt, X, y):
    """噪声下，以"模型预测分数最高的已测参数"作为当前最优，而不是单次实测最高分"""
    mean, sd = predict(opt, y, X)
    i = int(np.argmax(mean))
    return X[i], mean[i], sd[i]


# ================================== 子命令 ==================================


def cmd_check(args):
    print("读取数据：")
    X, y, is_new = load_all(verbose=True)
    print(f"  可用数据 {len(y)} 条（历史 {(~is_new).sum()} 条，新实验 {is_new.sum()} 条）")
    print(f"  分数范围 {y.min():.2f} ~ {y.max():.2f}")
    for i, v in enumerate(VARS):
        print(f"  {name(v)} 范围 {X[:, i].min():g} ~ {X[:, i].max():g}（允许 {BOUNDS[v][0]:g} ~ {BOUNDS[v][1]:g}）")
    _, counts = np.unique(X, axis=0, return_counts=True)
    if (counts > 1).any():
        print(f"  有 {(counts > 1).sum()} 组参数做过重复实验，可用于估计噪声")

    U = to_unit(X)
    y_pred = np.empty_like(y)
    for train, test in KFold(5, shuffle=True, random_state=SEED).split(U):
        model = make_model(U.shape[1])
        model.fit(U[train], y[train])
        y_pred[test] = np.ravel(model.predict(U[test]))
    r2, rmse = r2_score(y, y_pred), np.sqrt(np.mean((y - y_pred) ** 2))
    print(f"\n5 折交叉验证：R² = {r2:.3f}，预测误差 RMSE = {rmse:.2f} 分")
    if r2 < 0.3:
        print("⚠️ R² 偏低：频率/速度对分数的解释力有限（或噪声很大），建议先排查数据再做优化")
    else:
        print("模型能较好地预测分数，可以开始优化")


def cmd_ask(args):
    X, y, is_new = load_all()
    done = is_new.sum()
    if done >= MAX_NEW_EXPERIMENTS:
        print(f"⚠️ 已完成 {done} 次实验，达到计划上限 {MAX_NEW_EXPERIMENTS}（可在配置中调大）")
    opt = build_optimizer(X, y, args.n)
    X_next = from_unit(opt.ask())
    mean, sd = predict(opt, y, X_next)
    print(f"基于 {len(y)} 条数据（新实验 {done}/{MAX_NEW_EXPERIMENTS}），推荐下一批实验参数：")
    for i, x in enumerate(X_next):
        print(f"  #{i + 1}: {fmt_params(x)}   模型预测分数 ≈ {mean[i]:.1f} ± {sd[i]:.1f}")
    args_hint = " ".join(f"{x:.1f}" for x in X_next[0])
    print(f"\n做完实验后录入结果，例如：python trim_bo.py tell {args_hint} <分数>")
    print("（如果机台上实际设置的参数与推荐值不同，请录入实际值）")


def cmd_tell(args):
    x = np.array([args.freq, args.speed], dtype=float)
    for i, v in enumerate(VARS):
        if not LB[i] <= x[i] <= UB[i]:
            sys.exit(f"错误：{name(v)}={x[i]:g} 超出允许范围 {LB[i]:g} ~ {UB[i]:g}，未录入")
    if not np.isfinite(args.score):
        sys.exit("错误：分数必须是有效数字，未录入")

    X, y, _ = load_all()
    opt = build_optimizer(X, y)
    mean, sd = predict(opt, y, x)  # 录入前模型对这一点的预测，用来观察模型是否靠谱

    exps = load_experiments()
    row = {
        "时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
        COLUMNS["freq"]: x[0],
        COLUMNS["speed"]: x[1],
        COLUMNS["score"]: args.score,
        "备注": args.m or "",
    }
    exps = pd.concat([exps, pd.DataFrame([row])], ignore_index=True)
    exps.to_csv(path(EXPERIMENTS_FILE), index=False, encoding="utf-8-sig")

    print(f"已录入第 {len(exps)} 次实验：{fmt_params(x)}，分数 {args.score:g}")
    print(f"  录入前模型预测 {mean[0]:.1f} ± {sd[0]:.1f}，实测比预测{'高' if args.score > mean[0] else '低'} {abs(args.score - mean[0]):.1f} 分")
    if args.score > y.max():
        print(f"  🎉 超过此前所有数据的最高分 {y.max():.2f}")
    print(f"  剩余计划实验次数：{max(0, MAX_NEW_EXPERIMENTS - len(exps))}")


def cmd_status(args):
    X, y, is_new = load_all()
    exps = load_experiments()
    print(f"历史数据 {(~is_new).sum()} 条，新实验 {is_new.sum()}/{MAX_NEW_EXPERIMENTS} 次")
    if len(exps):
        print("\n新实验记录：")
        print(exps.fillna("").to_string(index=True))

    opt = build_optimizer(X, y)
    x_best, m, s = model_best(opt, X, y)
    i_obs = int(np.argmax(y))
    print(f"\n当前推荐的最优参数（模型预测最高的已测参数）：{fmt_params(x_best)}")
    print(f"  模型预测分数 {m:.1f} ± {s:.1f}")
    print(f"实测最高分 {y[i_obs]:.2f}（{fmt_params(X[i_obs])}，{'新实验' if is_new[i_obs] else '历史数据'}）")
    print("  注：单次实测最高分可能含正向噪声，以模型预测的最优参数为准更稳妥")


def cmd_undo(args):
    exps = load_experiments()
    if not len(exps):
        sys.exit("没有可删除的实验记录")
    last = exps.iloc[-1]
    exps.iloc[:-1].to_csv(path(EXPERIMENTS_FILE), index=False, encoding="utf-8-sig")
    print("已删除最后一条记录：" + ", ".join(f"{k}={v}" for k, v in last.items() if str(v) != "nan"))


def main():
    p = argparse.ArgumentParser(description="激光调阻参数的贝叶斯优化工具")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="检查数据，评估模型能否预测分数").set_defaults(func=cmd_check)
    a = sub.add_parser("ask", help="推荐下一组实验参数")
    a.add_argument("-n", type=int, default=1, help="一次推荐几组参数（默认 1）")
    a.set_defaults(func=cmd_ask)
    t = sub.add_parser("tell", help="录入一次实验结果")
    t.add_argument("freq", type=float, help=f"实际使用的{name('freq')}")
    t.add_argument("speed", type=float, help=f"实际使用的{name('speed')}")
    t.add_argument("score", type=float, help="按评估公式算出的分数")
    t.add_argument("-m", help="备注，例如批次号、异常情况")
    t.set_defaults(func=cmd_tell)
    sub.add_parser("status", help="查看进度和当前最优参数").set_defaults(func=cmd_status)
    sub.add_parser("undo", help="删除最后一条实验记录").set_defaults(func=cmd_undo)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
