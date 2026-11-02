# laser_trim

激光调阻工艺参数优化工具。告诉它**目标阻值**，它根据历史数据推荐**频率**和**修阻速度**；做完实验录入**良率**和 **FT SD**，它自动计算分数并更新下一次推荐。

```
输入：目标阻值（比如 1 MΩ）
优化：频率（10 / 50 / 100 kHz）+ 速度（5～15 mm/s）
跟随：功率、脉宽按频率固定搭配，见下表
评价：分数 = 0.5 × 良率 − 1 × FT SD，越高越好
```

频率、功率、脉宽在历史数据中只有 3 种固定搭配（下文称“配方”）：

| 频率 | 功率 | 脉宽 |
|---|---|---|
| 10 kHz | 0.811 W | 7.2 ns |
| 50 kHz | 3.142 W | 16.3 ns |
| 100 kHz | 0.966 W | 26 ns |

> ⚠️ 换频率时，功率和脉宽要一起换成表中对应的值，否则实际工艺与历史数据不一致，推荐就不再适用。

**目录**：[一、安装](#一安装每台电脑一次) ｜ [二、放入数据](#二放入数据) ｜ [三、日常使用](#三日常使用) ｜ [四、命令速查](#四命令速查) ｜ [五、怎么看结果](#五怎么看结果) ｜ [六、修改配置](#六修改配置) ｜ [七、更新](#七更新) ｜ [八、常见问题](#八常见问题)

---

## 一、安装（每台电脑一次）

### 1. 安装 uv

uv 用来管理 Python 环境，不需要事先安装 Python。

Linux / macOS：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

装完后**重新打开终端**，运行 `uv --version`，能看到版本号就成功了。

### 2. 配置 GitHub SSH 密钥

本项目通过 SSH 从 GitHub 下载。先安装 git，然后：

```bash
ssh-keygen -t ed25519 -C "你的邮箱"      # 一路回车
cat ~/.ssh/id_ed25519.pub                # 把输出的内容添加到 https://github.com/settings/keys
ssh -T git@github.com                    # 看到 "Hi xxx! You've successfully authenticated" 就成功了
```

如果仓库是私有的，还需要仓库所有者把你加为 `laser_trim` 仓库的协作者。

### 3. 下载代码并创建环境

```bash
git clone git@github.com:LesterZoeyXu/laser_trim.git
cd laser_trim
uv sync
```

`uv sync` 会自动准备 Python 3.12、创建 `.venv/` 虚拟环境，并安装所有依赖的锁定版本。第一次要下载几百 MB，之后有缓存会很快。

> 请用 `git clone`，不要用 GitHub 网页的 Download ZIP，否则以后无法用 `git pull` 更新。

---

## 二、放入数据

真实数据不在 GitHub 上，需要手动放进项目：

```
laser_trim/
└── data/
    └── AI参数优化项目数据统计.xlsx
```

没有 `data/` 目录就新建一个。放好后检查（约 3 分钟）：

```bash
uv run trim_bo.py check
```

正常的输出：

```
读取数据：
  data/AI参数优化项目数据统计.xlsx：去掉 4 条配方未知或速度超出 1~20 的记录
  可用数据 1375 条（历史 1375 条，新实验 0 条），目标阻值 44 种
  分数 = 0.5 × 良率 - 1 × FT SD，范围 -14.13 ~ 49.70
  ...
5 折交叉验证：
  已做过的目标阻值：R² = 0.876，预测误差 RMSE = 6.26 分
  没做过的目标阻值：R² = 0.838，预测误差 RMSE = 7.14 分
模型能较好地预测分数，可以开始优化
```

**R²** 表示模型预测得有多准，越接近 1 越好。大于 0.5 就可以开始优化；低于 0.3 要先排查数据，比如是否混入了其他工艺条件的数据。

手头没有真实数据时，可以用自带的模拟数据试用（在 `trim_bo.py` 后面加 `--history demo_history.csv`）。这份数据是编出来的，只用来熟悉命令：

```bash
uv run trim_bo.py --history demo_history.csv ask 1e5
```

---

## 三、日常使用

以优化 **1 MΩ** 为例。所有命令都在项目目录下运行，用 `uv run` 开头，不需要手动激活虚拟环境。除 `check` 外，每条命令约需 20 秒，`undo` 则立即完成。

### 第 1 步：看当前最优

```bash
uv run trim_bo.py status        # 所有 44 种目标阻值的推荐参数总表
uv run trim_bo.py status 1e6    # 只看 1 MΩ 的详情
```

如果只想知道现在该用什么参数，到这一步就够了。`status 1e6` 的输出：

```
1 MΩ 各配方的模型最优速度：
  100 kHz（功率(W)=0.966，脉宽(ns)=26），速度 7.5 mm/s   预测分数 37.2 ± 1.7
  50 kHz（功率(W)=3.142，脉宽(ns)=16.3），速度 6.5 mm/s   预测分数 29.7 ± 1.9
  10 kHz（功率(W)=0.811，脉宽(ns)=7.2），速度 5 mm/s   预测分数 10.2 ± 1.2

已测参数（按模型预测排序，前 5 组）：
    频率    速度  次数   良率%  FT SD  预测分数
100.00  7.00   3 83.46   0.79 37.13
100.00  9.00   3 80.99   0.98 36.87
...
```

### 第 2 步：获取下一组实验参数

```bash
uv run trim_bo.py ask 1e6
```

```
目标阻值 1 MΩ，基于 1375 条数据，当前模型最优分数 ≈ 37.1，推荐实验：
  #1: 100 kHz（功率(W)=0.966，脉宽(ns)=26），速度 7.5 mm/s   模型预测分数 ≈ 37.2 ± 1.7

做完实验后录入结果：uv run trim_bo.py tell 1000000 100 7.5 <良率%> <FT_SD>
```

### 第 3 步：上机台做实验

按推荐设置**频率、功率、脉宽和速度**，调阻后测出良率和 FT SD。

### 第 4 步：录入结果

依次填写：**目标阻值 频率 速度 良率 FT_SD**。

```bash
uv run trim_bo.py tell 1e6 100 7.5 86 0.6
uv run trim_bo.py tell 1e6 100 7.5 86 0.6 -m "批次A，第2盘"    # 也可以附带备注
```

```
已录入第 1 次实验：1 MΩ，100 kHz，7.5 mm/s，分数 42.40
  录入前模型预测 37.2 ± 1.7，实测比预测高 5.2 分
```

- 分数由工具自动计算，不用自己算。
- 良率填百分数，92.5% 就填 `92.5`，不要填 `0.925`。
- 录入**机台上实际使用的参数**。如果和推荐值不一样，以实际值为准。

### 第 5 步：回到第 1 步

录入的数据下次运行时会自动参与训练。一般这样循环几轮，直到推荐的预测分数不再比“当前模型最优分数”明显更高，就可以停了。

**一批做多组实验**：用 `-n` 一次获取多组推荐，做完后逐条 `tell`。

```bash
uv run trim_bo.py ask 1e6 -n 3
```

**录错了**：`uv run trim_bo.py undo` 删除最后一条。更早的记录可以用 Excel 打开 `experiments.csv` 修改。

---

## 四、命令速查

| 命令 | 作用 |
|---|---|
| `uv run trim_bo.py check` | 检查数据，评估模型准确度 |
| `uv run trim_bo.py status` | 查看所有目标阻值的推荐参数 |
| `uv run trim_bo.py status 1e6` | 查看 1 MΩ 的详情 |
| `uv run trim_bo.py ask 1e6` | 推荐 1 MΩ 的下一组实验 |
| `uv run trim_bo.py ask 1e6 -n 3` | 一次推荐 3 组 |
| `uv run trim_bo.py tell 1e6 100 7.5 86 0.6` | 录入：阻值 频率 速度 良率 SD |
| `uv run trim_bo.py tell ... -m "备注"` | 录入时附带备注 |
| `uv run trim_bo.py undo` | 删除最后一条录入 |
| `uv run trim_bo.py --help` | 查看帮助 |

目标阻值的单位是 Ω，可以写成 `1e6`，也可以写成 `1000000`：

| 阻值 | 写法 |
|---|---|
| 90 Ω | `90` |
| 100 kΩ | `1e5` 或 `100000` |
| 1 MΩ | `1e6` |
| 1.05 MΩ | `1.05e6` |
| 10 MΩ | `1e7` |

---

## 五、怎么看结果

**预测分数 37.2 ± 1.7**：模型估计分数约 37.2，± 后面是不确定度，越小说明模型越有把握。

**“当前模型最优”和“实测最高分”**：最终采用参数时，看 `status` 给出的模型最优参数，不要只看某一次实测的最高分。同样条件重复实验，良率可能相差十几个点，单次高分可能只是运气好。

**`status` 总表最后一列“次数”**：表示这组参数实测过几次。只测过 1 次的，投产前建议重复验证。

**推荐速度总是 5 或 15 mm/s**：这是搜索范围的边界，真正的最优值可能在范围外。可以补做 3 或 20 mm/s 的实验，再调大 `SEARCH_SPEED`。

**预测分数一直很低**：比如 15 Ω（预测约 -1.7）。目标阻值比初始阻值高太多时，调工艺参数也很难救回来，要考虑初始阻值或设计。

**没做过的目标阻值**：`ask` 会给出提示，结果来自相邻阻值的插值。附近没有数据时不确定度会很大，比如 3 MΩ 约为 ±23，这种推荐只能作为参考。超出 1 Ω～10 MΩ 的阻值会被拒绝。

**初始阻值变了**：模型没有使用初始阻值。如果新批次的初始阻值和历史数据差别较大，预测可能不准。

---

## 六、修改配置

配置都在 `trim_bo.py` 开头：

```python
HISTORY_FILE = "data/AI参数优化项目数据统计.xlsx"    # 历史数据文件
HEADER_ROW = 2                       # Excel 中列名所在行（从 0 开始数）
COLUMNS = {...}                      # 程序用名 -> 文件里的列名
RECIPES = {10: {...}, 50: {...}, 100: {...}}  # 3 个配方：频率 -> 功率、脉宽
VALID_SPEED = (1.0, 20.0)            # 设备允许的速度，超出的历史记录不参与训练
SEARCH_SPEED = (5.0, 15.0)           # 推荐时搜索的速度范围
SPEED_STEP = 0.5                     # 推荐速度的步长，机台只能设整数时改成 1
BATCH_MIN_GAP = 2.0                  # ask -n 时，同一配方的速度至少相隔多少
YIELD_WEIGHT, SD_WEIGHT = 0.5, 1.0   # 分数 = 0.5 × 良率 - 1 × FT SD
```

- **更看重精度**：调大 `SD_WEIGHT`。已有数据和新实验的分数都会按新公式重新计算。
- **换了新的数据文件**：改 `HISTORY_FILE`。如果列名不同，再改 `COLUMNS`。CSV 文件的列名要在第一行。
- **`SEARCH_SPEED`** 应设为工艺上能稳定做出合格品的区间，不要设成机台的物理极限。

---

## 七、更新

```bash
git pull && uv sync                          # 获取最新代码，并同步环境
uv add scipy                                 # 需要新增依赖时（会自动更新 pyproject.toml 和 uv.lock）
```

修改 `pyproject.toml` / `uv.lock` 后记得提交，这样其他人 `uv sync` 时得到的环境与你一致。

### 更新 bayes-optim

`bayes-optim` 不从 GitHub 现场构建，而是安装 `wheels/` 里预先构建好的安装包，所以任何系统上 `uv sync` 都不需要构建，也不需要 `BayesianOp` 仓库的权限。`BayesianOp` 有新修复时，在 Linux 或 Mac 上重新构建并替换：

```bash
cd ../Bayesian-Optimization && git pull          # BayesianOp 仓库的本地克隆
uv build --wheel -o ../laser_trim/wheels .       # 生成新的 bayes_optim-*.whl
cd ../laser_trim
uv lock --upgrade-package bayes-optim && uv sync # 更新锁定版本并同步环境
```

如果版本号变了，文件名也会变，要同步修改 `pyproject.toml` 里的路径，并删掉旧的 wheel。改完后提交 `wheels/`、`pyproject.toml` 和 `uv.lock`。

### 数据和实验记录

`data/`、`.xlsx`、`.xls` 和 `experiments.csv` 都已被 git 忽略，**不会上传到 GitHub，也不会随 `git pull` 同步**：

- 换电脑时，要手动复制 `data/` 和 `experiments.csv`。
- `experiments.csv` 是你的实验记录，请自行备份。

---

## 八、常见问题

**`error: No pyproject.toml found`**
当前不在项目目录里。先 `cd laser_trim`，再用 `ls` 确认能看到 `pyproject.toml`。如果是从网页下载 ZIP 解压的，可能多套了一层目录，建议改用 `git clone`。

**`错误：找不到数据文件`**
Excel 没有放到 `data/` 目录下，或者文件名不一致，见[第二节](#二放入数据)。

**`git clone` 报 `Permission denied (publickey)` 或 `Host key verification failed`**
SSH 密钥没有配置好，或者第一次连接 GitHub 还没确认主机。运行 `ssh -T git@github.com`，按提示输入 `yes`，看到 `Hi xxx!` 即可。

**`uv: command not found`**
安装 uv 后没有重新打开终端。重开终端，或按安装脚本最后的提示把 uv 加入 `PATH`。

**`错误：频率只能是 [10, 50, 100] kHz，未录入`**
目前只支持这 3 个配方。`tell` 的参数顺序是：目标阻值、频率、速度、良率、FT SD，也请检查顺序是否写错。

**`tell` / `undo` 写入失败（Windows）**
`experiments.csv` 正在被 Excel 打开，关闭后再运行。

**能不能不用 `uv run`？**
可以先激活虚拟环境，再用 `python trim_bo.py`：Linux/macOS 运行 `source .venv/bin/activate`，Windows 运行 `.venv\Scripts\activate`。

**支持哪些系统？**
Linux（x86_64 / ARM）、Windows、Apple Silicon 的 Mac。Intel 芯片的 Mac 不支持（torch 已不再为其提供安装包）。

---

## 其他文档

- [GP（高斯过程）模型的训练原理](docs/gp_training.md)：GP 的假设、最大似然训练过程、预测与 EI 推荐。
- [trim_bo_1ohm.py 使用教程](docs/trim_bo_1ohm.md)：1 Ω 段简化版工具，只用频率和速度两个参数。

`demo_history.csv` 是 `make_demo_data.py` 生成的**模拟数据**，列名与真实数据一致，不代表真实工艺规律。重新生成：`uv run make_demo_data.py`。
