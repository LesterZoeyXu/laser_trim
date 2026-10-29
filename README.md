# laser_trim

用贝叶斯优化调试激光调阻的**频率**和**调阻速度**：用历史数据热启动，之后每做一次实验录入分数，工具推荐下一组参数。

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

### 第 3 步：用演示数据试运行

仓库自带一份**模拟**的历史数据 `demo_history.csv`，可以直接试用。所有命令都用 `uv run` 执行，它会自动使用项目的 `.venv` 环境，**不需要手动激活虚拟环境**：

```bash
uv run trim_bo.py check     # 检查数据：可用条数、参数范围、模型交叉验证 R²
uv run trim_bo.py ask       # 推荐下一组实验参数
uv run trim_bo.py --help    # 查看所有命令
```

### 第 4 步：换成你的真实数据

1. 把历史数据放进项目目录（支持 `.csv`、`.xlsx`），至少包含频率、速度、分数三列。
2. 打开 `trim_bo.py`，修改开头的配置区：

   ```python
   HISTORY_FILE = "我的历史数据.xlsx"                         # 数据文件名
   COLUMNS = {"freq": "频率", "speed": "速度", "score": "分数"}  # 右边改成文件里的实际列名
   UNITS = {"freq": "kHz", "speed": "mm/s"}
   BOUNDS = {"freq": (20.0, 100.0), "speed": (10.0, 200.0)}    # 允许搜索的范围
   MAX_NEW_EXPERIMENTS = 20                                    # 计划再做多少次实验
   ```

   > ⚠️ `BOUNDS` 应设为**工艺上能稳定做出合格品**的区间，而不是机台的物理极限。BO 会主动去没有数据的区域探索，范围设得太宽可能会推荐出做废品的参数。

3. 运行 `uv run trim_bo.py check`，重点看交叉验证的 **R²**：
   - R² 较高（如 > 0.5）：模型能抓住频率/速度与分数的关系，可以开始优化
   - R² 很低（< 0.3）：先排查数据，例如是否混入了不同电阻型号、激光功率等其他工艺条件的数据

真实数据文件（`.xlsx`、`.xls`、`data/` 目录）和实验记录 `experiments.csv` 已在 `.gitignore` 中排除，不会被提交到 GitHub。

### 第 5 步：日常实验流程

每一轮重复以下步骤：

```bash
uv run trim_bo.py ask                       # 1. 获取推荐参数
                                            # 2. 在机台上按推荐参数调阻、测量，用评估公式算出分数
uv run trim_bo.py tell 63.0 104 90.1        # 3. 录入：频率 速度 分数
uv run trim_bo.py tell 63.0 104 90.1 -m "批次A，第2盘"   #    也可以附带备注
uv run trim_bo.py status                    # 4. 随时查看进度和当前最优参数
```

- **录入机台上实际使用的参数**。如果机台只能设整数等原因导致与推荐值不同，以实际值为准。
- **录错了**：`uv run trim_bo.py undo` 删除最后一条；更早的记录可以直接用 Excel 打开 `experiments.csv` 修改。
- **Windows 用户注意**：运行 `tell` / `undo` 前请先关闭 Excel 中打开的 `experiments.csv`，否则文件被占用会写入失败。
- **一批做多组实验**：`uv run trim_bo.py ask -n 3` 一次推荐 3 组，做完后逐条 `tell`。
- **最终采用哪组参数**：以 `status` 给出的"模型预测最高的已测参数"为准，而不是某一次实测的最高分（单次实测包含噪声）。

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

## 演示数据

`demo_history.csv` 是 `make_demo_data.py` 生成的**模拟数据**，不代表真实工艺规律，仅用于演示和测试。重新生成：`uv run make_demo_data.py`。
