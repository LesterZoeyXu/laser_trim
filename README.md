# laser_trim

用贝叶斯优化调试激光调阻的**频率**和**调阻速度**：用历史数据热启动，之后每做一次实验录入分数，工具推荐下一组参数。

## 安装

```bash
python -m venv .venv
# torch 是 bayes-optim 的依赖；只用 CPU 版可以省下几 GB
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
```

## 使用

先修改 `trim_bo.py` 开头的配置区：历史数据文件、列名、频率/速度允许的范围、计划实验次数。

```bash
python trim_bo.py check                         # 检查数据，评估模型能否预测分数
python trim_bo.py ask                           # 推荐下一组参数（-n 3 一次推荐 3 组）
python trim_bo.py tell 63.0 104 90.1 -m 批次A    # 录入一次实验：频率 速度 分数 [备注]
python trim_bo.py status                        # 查看进度和当前最优参数
python trim_bo.py undo                          # 删除最后一条记录（录错时用）
```

- 新实验记录在 `experiments.csv`，可以用 Excel 打开修改；每次运行都用"历史数据 + 实验记录"重新热启动，不保存优化器状态。
- 录入机台上**实际使用**的参数，而不一定是推荐值。
- `status` 给出的最优参数以模型预测为准，而非单次实测最高分（实测含噪声）。
- 搜索范围应设为工艺上能稳定做出合格品的区间，而不是机台的物理极限：BO 会主动探索没有数据的区域。

## 演示数据

`demo_history.csv` 是 `make_demo_data.py` 生成的**模拟数据**，不代表真实工艺规律，仅用于演示和测试。
真实数据和 `experiments.csv` 默认被 `.gitignore` 排除，不会提交到仓库。
