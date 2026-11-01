# laser_trim

用贝叶斯优化调试激光调阻工艺：对每个目标阻值，在 3 个固定配方（频率/功率/脉宽）和修阻速度中推荐下一组实验。用历史数据训练模型，之后每做一次实验录入良率和 FT SD，工具自动计算分数并更新推荐。

Python 环境用 [uv](https://docs.astral.sh/uv/) 管理：依赖写在 `pyproject.toml`，精确版本锁定在 `uv.lock`，任何机器上 `uv sync` 都能得到完全相同的环境。

---

## 教程

### 第 0 步：准备工作（每台电脑只需做一次）

**1. 安装 uv**

Linux / macOS：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

装完后**重新打开终端**，运行 `uv --version` 能看到版本号即可。不需要事先安装 Python —— uv 会自动下载本项目需要的 Python 3.12。

**2. 安装 git**，并在 GitHub 上配置好 SSH 密钥

本项目依赖的 `bayes-optim` 是从 GitHub 仓库 `LesterZoeyXu/BayesianOp` 通过 SSH 安装的，所以需要能用 SSH 访问 GitHub：

```bash
ssh-keygen -t ed25519 -C "你的邮箱"      # 一路回车即可
cat ~/.ssh/id_ed25519.pub                # 把输出的公钥添加到 https://github.com/settings/keys
ssh -T git@github.com                    # 看到 "Hi xxx! You've successfully authenticated" 即成功
```

如果仓库是私有的，还需要仓库所有者把你加为协作者。

### 第 1 步：获取代码

```bash
git clone git@github.com:LesterZoeyXu/laser_trim.git
cd laser_trim
```

### 第 2 步：创建 Python 环境

```bash
uv sync
```

这一条命令会：

1. 按 `.python-version` 准备 Python 3.12（本机没有的话自动下载）
2. 在项目目录下创建虚拟环境 `.venv/`
3. 按 `uv.lock` 安装所有依赖的精确版本，包括 CPU 版 torch 和修复过的 `bayes-optim`

第一次运行需要下载约几百 MB（主要是 torch），之后有缓存会很快。

### 第 3 步：放入数据并检查

历史数据 `AI参数优化项目数据统计.xlsx` 不提交到 GitHub，需要手动放到项目的 `data/` 目录下。所有命令都用 `uv run` 执行，它会自动使用项目的 `.venv` 环境，**不需要手动激活虚拟环境**：

```bash
uv run trim_bo.py check     # 检查数据：可用条数、各配方情况、模型交叉验证 R²（约 3 分钟）
uv run trim_bo.py --help    # 查看所有命令
```

手头没有真实数据时，可以用仓库自带的**模拟**数据试用，在命令里加 `--history demo_history.csv`：

```bash
uv run trim_bo.py --history demo_history.csv ask 1e5
```

### 第 4 步：确认配置

`trim_bo.py` 开头的配置区：

```python
HISTORY_FILE = "data/AI参数优化项目数据统计.xlsx"
HEADER_ROW = 2                       # Excel 中列名所在行（从 0 开始数）
COLUMNS = {...}                      # 程序用名 -> 文件里的列名
RECIPES = {10: {...}, 50: {...}, 100: {...}}  # 3 个固定配方：频率 -> 功率、脉宽
VALID_SPEED = (1.0, 20.0)            # 设备允许的速度，超出的历史记录不参与训练
SEARCH_SPEED = (5.0, 15.0)           # 推荐时搜索的速度范围
SPEED_STEP = 0.5                     # 推荐速度的步长，机台只能设整数时改成 1
YIELD_WEIGHT, SD_WEIGHT = 0.5, 1.0   # 分数 = 0.5 × 良率 - 1 × FT SD
```

> ⚠️ `SEARCH_SPEED` 应设为**工艺上能稳定做出合格品**的区间。历史数据大多在 5～15 mm/s，范围外数据很少，模型把握不大。

`check` 中重点看交叉验证的 **R²**：

- R² 较高（如 > 0.5）：模型能抓住工艺参数与分数的关系，可以开始优化
- R² 很低（< 0.3）：先排查数据，例如是否混入了其他工艺条件的数据

真实数据文件（`.xlsx`、`.xls`、`data/` 目录）和实验记录 `experiments.csv` 已在 `.gitignore` 中排除，不会被提交到 GitHub。

### 第 5 步：日常实验流程

**先看所有目标阻值的当前最优参数：**

```bash
uv run trim_bo.py status        # 44 种目标阻值的推荐配方、速度、预测分数
uv run trim_bo.py status 1e6    # 只看 1 MΩ：各配方的最优速度和已测结果
```

**再针对某个目标阻值做实验，每一轮重复：**

```bash
uv run trim_bo.py ask 1e6                     # 1. 获取推荐：配方和速度
                                              # 2. 在机台上按推荐参数调阻，测量良率和 FT SD
uv run trim_bo.py tell 1e6 100 7.5 86 0.6     # 3. 录入：目标阻值 频率 速度 良率 FT_SD，分数自动计算
uv run trim_bo.py tell 1e6 100 7.5 86 0.6 -m "批次A，第2盘"   #    也可以附带备注
```

- 目标阻值可以写成 `1e6`，也可以写成 `1000000`。
- 频率只能是 10、50、100，功率和脉宽按配方设置。
- 没做过的目标阻值也能 `ask`，但结果来自相邻阻值的插值，工具会给出提示，把握较低。超出数据范围的阻值会被拒绝。
- **录入机台上实际使用的参数**。如果与推荐值不同，以实际值为准。
- **录错了**：`uv run trim_bo.py undo` 删除最后一条；更早的记录可以直接用 Excel 打开 `experiments.csv` 修改。
- **Windows 用户注意**：运行 `tell` / `undo` 前请先关闭 Excel 中打开的 `experiments.csv`，否则文件被占用会写入失败。
- **一批做多组实验**：`uv run trim_bo.py ask 1e6 -n 3` 一次推荐 3 组，做完后逐条 `tell`。
- **最终采用哪组参数**：以 `status` 给出的"模型预测最高的已测参数"为准，而不是某一次实测的最高分（单次实测包含噪声）。

每条命令都会重新训练模型，`ask` / `tell` / `status` 约需 20 秒。

### 第 6 步：更新与维护

```bash
git pull && uv sync                          # 获取最新代码，并同步环境
uv lock --upgrade-package bayes-optim        # BayesianOp 仓库有新修复时，更新到最新版本
uv sync                                      # 然后同步环境
uv add scipy                                 # 需要新增依赖时（会自动更新 pyproject.toml 和 uv.lock）
```

修改 `pyproject.toml` / `uv.lock` 后记得提交，这样其他人 `uv sync` 时得到的环境与你一致。

---

## 常见问题

**`uv sync` 报 `Permission denied (publickey)`**
SSH 密钥没有配置好，或者没有 `BayesianOp` 仓库的访问权限。按第 0 步检查 `ssh -T git@github.com`。

**`uv: command not found`**
安装 uv 后没有重新打开终端。重开终端，或按安装脚本最后的提示把 uv 加入 `PATH`。

**能不能不用 `uv run`？**
可以先激活虚拟环境，再直接用 `python`：Linux/macOS 运行 `source .venv/bin/activate`，Windows 运行 `.venv\Scripts\activate`。

**支持哪些系统？**
Linux（x86_64 / ARM）、Windows、Apple Silicon 的 Mac。Intel 芯片的 Mac 不支持（torch 已不再为其提供安装包）。

---

## 原理文档

- [GP（高斯过程）模型的训练原理](docs/gp_training.md)：GP 的假设、最大似然训练过程、预测与 EI 推荐。

---

## 演示数据

`demo_history.csv` 是 `make_demo_data.py` 生成的**模拟数据**，列名与真实数据一致，不代表真实工艺规律，仅用于演示和测试。重新生成：`uv run make_demo_data.py`。
