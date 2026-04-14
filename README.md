# 分布式共识实验平台（Multi-Layer HotStuff + 实验分析）

这个仓库现在包含两部分内容：

- 在线共识系统：基于 `Vue 3 + FastAPI + Socket.IO` 的交互式 Multi-Layer HotStuff 演示与实验平台。
- 离线实验分析：基于 Python 的数据处理、理论建模、拟合与绘图脚本（含多份 `csv` 与 `fig_*.png` 产物）。

> 说明：仓库中仍可能保留少量 `PBFT` 命名（如旧组件名/历史文档），主要为历史兼容与迁移遗留，当前主线协议以 Multi-Layer HotStuff 为准。

---

## 1) 在线共识系统

### 主要能力

- 主控端创建会话、配置参数、生成二维码/加入链接
- 参与者按节点加入并完成实时消息交互
- 可视化展示拓扑、阶段进度和结果统计
- 支持拜占庭相关实验开关（恶意提议/消息篡改等场景）
- 后端支持会话持久化与恢复（SQLite）

### 技术栈

- 前端：Vue 3、Element Plus、Pinia、Vue Router、Socket.IO Client、ECharts
- 后端：FastAPI、python-socketio、Pydantic、Uvicorn

### 快速启动

#### Windows（推荐）

```bat
start.bat
```

#### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

#### 手动启动

```bash
# 前端依赖
npm install

# 后端依赖
cd backend
pip install -r requirements.txt
python main.py

# 新终端启动前端
cd ..
npm run dev
```

默认地址：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`

### 基本使用流程

1. 主控端打开首页，创建会话并设置参数
2. 参与者扫描二维码或打开链接进入节点页面
3. 各节点实时参与共识流程
4. 查看阶段状态、消息与最终结果

---

## 2) 离线实验分析与建模

仓库根目录包含一组实验与理论分析脚本，典型用途是：

- 汇总不同 `N`（节点数）与 `Delivery Rate` 下的可靠性实验结果
- 构建理论模型并与实验数据对比
- 生成论文/报告使用的图像与表格

### 常用脚本（根目录）

- `plot_all_phases.py`：批量绘制各阶段和多 DR 的可靠性图
- `final_analysis.py`：综合分析与高质量图产出（含理论对比）
- `mathematical_model.py`：理论模型计算
- `calibrate_model.py`：模型参数拟合
- `plot_results.py`：结果绘图与可视化

### 输入与输出

- 输入：`Experiment2_*.csv`、`theory_vs_experiment.csv`
- 输出：`fig_*.png`、分析中间结果与报告素材

### 运行分析脚本

如果本机尚未安装分析依赖，可先执行：

```bash
pip install numpy pandas matplotlib scipy
```

然后运行示例：

```bash
python plot_all_phases.py
python final_analysis.py
```

---

## 3) 当前项目结构（简版）

```text
d:/block_chain
├── src/                      # 前端代码（页面、组件、状态管理）
├── backend/                  # 后端代码（API、Socket、共识逻辑、持久化）
├── start.bat / start.sh      # 一键启动脚本
├── test_*.py                 # 若干测试脚本
├── Experiment2_*.csv         # 实验数据
├── fig_*.png                 # 绘图输出
├── *_analysis.py / *_model.py
└── README.md
```

> 更细的代码结构可参考 `PROJECT_STRUCTURE.md`。

---

## 4) 相关文档导航

- `PROJECT_STRUCTURE.md`：项目结构说明
- `启动说明.md`：中文启动说明
- `ANIMATION_DEMO_GUIDE.md`：演示相关说明
- `REALTIME_ONLY_UPDATE.md`、`MULTI_ROUND_SUPPORT.md`：功能迭代记录
- `BUG_FIX_404.md`、`STATS_FIX.md` 等：问题修复记录

---

## 5) 说明

- 本仓库同时服务于“在线交互系统开发”和“实验分析/论文图表产出”两类工作流。
- 如果你只关注 Web 系统，可优先看 `src/`、`backend/`、`start.bat`。
- 如果你只关注实验分析，可优先看根目录的 `*_analysis.py`、`*_model.py`、`Experiment2_*.csv`。