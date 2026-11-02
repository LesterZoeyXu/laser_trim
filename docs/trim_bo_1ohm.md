# trim_bo_1ohm.py 使用教程

`trim_bo_1ohm.py` 是 1 Ω 段（目标阻值 1、1.1、1.15、1.2 Ω）的简化版优化工具：用一个高斯过程（GP）模型，根据**频率**和**速度**预测分数，并推荐下一组实验。

```
输入：频率（10～100 kHz）、速度（5～15 mm/s）
评价：分数 = 0.5 × 良率 − 1 × FT SD，越高越好
```

**目录**：[一、安装](#一安装每台电脑只做一次) ｜ [二、放入数据](#二放入数据) ｜ [三、检查数据和模型](#三检查数据和模型) ｜ [四、日常使用](#四日常使用) ｜ [五、命令速查](#五命令速查) ｜ [六、修改配置](#六修改配置) ｜ [七、注意事项](#七注意事项) ｜ [八、常见问题](#八常见问题)

---

## 一、安装（每台电脑只做一次）

### 1. 安装 uv

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Linux / Mac：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

装完后**重新打开终端**，运行 `uv --version`，能看到版本号就成功了。

### 2. 配置 GitHub SSH 密钥

```bash
ssh -T git@github.com
```

- 第一次连接时，先核对指纹是 `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`，再输入 `yes`。
- 看到 `Hi xxx!` 就可以了。
- 如果提示 `Permission denied`，先生成密钥（**已有密钥时不要覆盖**）：

  ```bash
  ssh-keygen -t ed25519 -C "你的邮箱"
  ```

  再把 `.pub` 文件的内容添加到 <https://github.com/settings/keys>。

### 3. 下载代码并安装依赖

```bash
git clone git@github.com:LesterZoeyXu/laser_trim.git
cd laser_trim
uv sync
```

已经克隆过的，进入项目目录更新即可：

```bash
git pull
uv sync
```

---

## 二、放入数据

训练数据 `simple_data_1ohm.csv` **不在 GitHub 上**，用下面任一方法准备好。

**方法一：从原始 Excel 生成（推荐）**

把原始数据 `AI参数优化项目数据统计.xlsx` 放进 `data/` 目录（没有就新建），然后运行：

```bash
uv run make_simple_data.py
```

```
读取 data/AI参数优化项目数据统计.xlsx：1379 条，去掉缺失 0 条、速度超出 1~20 的 4 条
目标阻值 0.5 ~ 2 Ω：70 条，包含阻值 [1.0, 1.1, 1.15, 1.2]
已写入 data/simple_data_1ohm.csv
```

只想要某个阻值，用 `--min`、`--max` 指定范围，用 `-o` 指定输出文件，例如只要 1 Ω：

```bash
uv run make_simple_data.py --min 0.9 --max 1.05 -o data/simple_data_1ohm_only.csv
```

用了其他文件名时，记得同步修改 `trim_bo_1ohm.py` 里的 `HISTORY_FILE`。

**方法二：直接复制**

从已有的电脑把 `simple_data_1ohm.csv` 复制过来。

两种方法得到的文件位置都是：

```
laser_trim/
└── data/
    ├── AI参数优化项目数据统计.xlsx   （方法一需要）
    └── simple_data_1ohm.csv
```

CSV 第 1 行是列名，必须包含这 4 列：

```
频率(kHz),速度(mm/s),良率(%),FT SD(%)
```

有“分数”列也没关系，工具会忽略它，用 `0.5 × 良率 − FT SD` 自己计算。

---

## 三、检查数据和模型

```bash
uv run trim_bo_1ohm.py check
```

正常的输出：

```
1 Ω 段数据 70 条，分数范围 -4.16 ~ 32.45
  10 kHz：22 条，平均分 4.6
  50 kHz：24 条，平均分 13.2
  100 kHz：24 条，平均分 10.1

5 折交叉验证：R² = 0.167，预测误差 RMSE = 7.55 分
```

**R²** 越接近 1，模型预测越准。现在只有 0.167，推荐结果只能作为参考，要以实验结果为准。

---

## 四、日常使用

### 第 1 步：查看已测参数的排名

```bash
uv run trim_bo_1ohm.py status            # 前 10 组
uv run trim_bo_1ohm.py status --top 5    # 前 5 组
```

```
1 Ω 段数据 70 条，新实验 0 条，已测参数排名（前 10 组）：
    频率    速度  次数   良率%  FT SD  预测分数
 50.00 15.00   4 35.93   0.78 15.53
 50.00 13.00   4 38.24   0.87 15.23
 ...
```

“预测分数”比单次实测更可靠，因为实测有噪声，模型会参考相邻实验的结果做平滑。

### 第 2 步：获取推荐

```bash
uv run trim_bo_1ohm.py ask          # 推荐 1 组
uv run trim_bo_1ohm.py ask -n 3     # 一次推荐 3 组
```

```
基于 70 条 1 Ω 段数据，当前模型最优分数 ≈ 15.5，采集函数 UCB（κ=2），推荐实验：
  #1: 55 kHz，速度 15 mm/s   模型预测分数 ≈ 10.3 ± 5.0

做完实验后录入结果：uv run trim_bo_1ohm.py tell 55 15 <良率%> <FT_SD>
```

`±` 后面是不确定度，越大说明模型越没把握。

**采集函数**：默认用 UCB（置信上界），UCB = 预测分数 + κ × 不确定度，κ 默认 2。κ 越大越偏向探索没试过的参数，越小越保守。也可以改用 EI（期望改进），它会自动平衡“在已知好区域附近挖掘”和“去没试过的地方探索”：

```bash
uv run trim_bo_1ohm.py ask                    # UCB，κ = 2（默认）
uv run trim_bo_1ohm.py ask --kappa 1          # UCB，κ = 1，更保守
uv run trim_bo_1ohm.py ask --acq ei           # 改用 EI
```

用现在的数据实测：

| 设置 | 推荐 |
|---|---|
| UCB，κ = 2 或 3（默认 κ = 2） | 55 kHz 等中间频率，去探索没有数据的地方 |
| UCB，κ = 0 或 1 | 50 kHz，14.5～15 mm/s，留在已知的好区域 |
| EI | 50 kHz，15 mm/s |

### 第 3 步：上机台做实验

按推荐的频率和速度调阻，测出良率和 FT SD。

### 第 4 步：录入结果

参数顺序是：**频率 速度 良率 FT_SD**。

```bash
uv run trim_bo_1ohm.py tell 50 15 40 0.9
uv run trim_bo_1ohm.py tell 50 15 40 0.9 -m "1 Ω，批次A"
```

```
已录入第 1 次实验：50 kHz，15 mm/s，分数 19.10
```

- 良率填百分数，比如 92.5% 填 `92.5`，不要填 `0.925`。
- 频率可以是 10～100 kHz 之间的任意值，比如 `72.5`。
- 录入**机台上实际使用的值**，和推荐值不同时以实际值为准。

### 第 5 步：回到第 1 步

录入的数据下次运行时会自动参与训练。循环几轮，直到推荐的预测分数不再明显高于“当前模型最优分数”。

### 录错了

```bash
uv run trim_bo_1ohm.py undo     # 删除最后一条
```

更早的记录可以用 Excel 打开 `experiments_1ohm.csv` 修改。

---

## 五、命令速查

| 命令 | 作用 |
|---|---|
| `uv run trim_bo_1ohm.py check` | 检查数据，评估模型准确度 |
| `uv run trim_bo_1ohm.py status` | 已测参数排名（`--top N` 控制显示几组） |
| `uv run trim_bo_1ohm.py ask` | 推荐下一组实验（`-n N` 一次推荐 N 组，`--acq ei` 改用 EI，`--kappa` 调 UCB 的 κ） |
| `uv run trim_bo_1ohm.py tell 频率 速度 良率 SD` | 录入实验结果（`-m` 加备注） |
| `uv run trim_bo_1ohm.py undo` | 删除最后一条录入 |
| `uv run trim_bo_1ohm.py --help` | 查看帮助 |
| `uv run make_simple_data.py` | 从原始 Excel 生成训练数据 |

---

## 六、修改配置

配置在 `trim_bo_1ohm.py` 开头：

```python
HISTORY_FILE = "data/simple_data_1ohm.csv"   # 训练数据
EXPERIMENTS_FILE = "experiments_1ohm.csv"    # 新实验记录（tell 自动维护）
FREQ_RANGE = (10.0, 100.0)    # 推荐时的频率范围(kHz)
FREQ_STEP = 5.0               # 频率步长
SPEED_RANGE = (5.0, 15.0)     # 推荐时的速度范围(mm/s)
SPEED_STEP = 0.5              # 速度步长，机台只能设整数时改成 1
BATCH_MIN_GAP = 2.0           # ask -n 时，频率相近的两组，速度至少相隔多少 mm/s
BATCH_FREQ_GAP = 15.0         # ask -n 时，频率相差不到这么多 kHz 就算相近
UCB_KAPPA = 2.0               # UCB 的 κ 默认值
YIELD_WEIGHT, SD_WEIGHT = 0.5, 1.0   # 分数 = 0.5 × 良率 − 1 × FT SD
SEED = 42                     # 随机种子，保证同样的数据每次结果相同
```

- **更看重精度**：调大 `SD_WEIGHT`。
- **一批推荐想更分散**：调大 `BATCH_FREQ_GAP`，比如 30。
- **换训练数据**：改 `HISTORY_FILE`，新文件的列名要和上面一致。

---

## 七、注意事项

- **中间频率没有数据**：历史数据只有 10、50、100 kHz，中间频率的预测只是平均水平。补做中间频率的实验后，推荐才会变得有意义。
- **4 种阻值混在一起**：训练数据包含 1、1.1、1.15、1.2 Ω，模型分不出来。新实验最好都用同一种阻值，并写在 `-m` 备注里。
- **搜索范围的边界**：推荐落在 15 mm/s 时，最优速度可能更高，可以补做更高速度的实验，再调大 `SPEED_RANGE`。
- **实验记录要自己备份**：记录存在 `experiments_1ohm.csv`，只保存在本机，不会上传到 GitHub。它和 `trim_bo.py` 的 `experiments.csv` 互不影响。
- **Windows 上要先关掉 Excel**：运行 `tell` 或 `undo` 之前，要先关闭 Excel 里打开的 `experiments_1ohm.csv`，否则会写入失败。
- **运行速度**：每次大约几秒，大部分时间在加载库。

---

## 八、常见问题

| 报错 | 解决 |
|---|---|
| `No pyproject.toml found` | 没在项目目录里，先 `cd laser_trim` |
| `错误：找不到数据文件` | `data/simple_data_1ohm.csv` 没放好，见[第二节](#二放入数据) |
| `make_simple_data.py` 报 `找不到` | 原始 Excel 没放进 `data/`，或文件名不一致，可以用 `-i` 指定 |
| `Host key verification failed` | 运行 `ssh -T git@github.com`，核对指纹后输入 `yes` |
| `Permission denied (publickey)` | SSH 密钥没配置，见[安装第 2 步](#2-配置-github-ssh-密钥) |
| `uv: command not found` | 装完 uv 后重新打开终端 |
| `错误：频率 ... 超出范围` | 频率要在 `FREQ_RANGE`（默认 10～100 kHz）以内 |
