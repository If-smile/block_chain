# Multi-Layer HotStuff 分布式共识实验平台

这是一个基于 `Vue 3 + FastAPI + Socket.IO` 的交互式共识实验系统，协议为 **Multi-Layer HotStuff**。  
项目支持在线多节点协作、拜占庭场景开关、Monte Carlo 无头仿真，以及会话状态持久化恢复。

## 核心能力

- **会话创建与参数配置**：节点数、故障节点、网络拓扑、分组数、提议内容等
- **实时共识交互**：节点接入、阶段推进、消息广播、状态同步
- **分层 HotStuff 机制**：分组投票聚合，降低全局 Leader 通信压力
- **拜占庭实验支持**：恶意 Leader、消息篡改、消息送达率控制
- **无头仿真接口**：后端批量运行多轮并返回可靠性、首视图成功率、平均时延
- **持久化恢复**：会话与历史写入 SQLite，服务重启后自动恢复

## 技术栈

- **前端**：Vue 3、Element Plus、Pinia、Vue Router、ECharts、Socket.IO Client
- **后端**：FastAPI、python-socketio、Pydantic、Uvicorn、SQLite

## 快速启动

### Windows（推荐）

```bat
start.bat
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

### 手动启动

```bash
# 安装前端依赖
npm install

# 启动后端
cd backend
pip install -r requirements.txt
python main.py

# 新终端启动前端
cd ..
npm run dev
```

默认访问地址：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000`

## 使用流程

1. 在首页创建会话并设置参数
2. 通过二维码或链接让参与者加入对应节点
3. 观察阶段推进、消息审计与共识结果
4. 按需运行 Monte Carlo 仿真评估可靠性

## 协议与仿真说明

- **协议主线**：Multi-Layer HotStuff（含 view/leader 轮转与 QC 驱动阶段推进）
- **仿真接口**：`POST /api/simulate`
  - 输入：会话配置 + 轮次（`rounds`）
  - 输出：可靠性、首视图成功率、成功轮次、平均时延、进度事件
- **会话接口**：`POST /api/sessions` 创建在线会话

## 项目结构（当前常用）

```text
d:/block_chain
├── src/
│   ├── views/                # HomePage / JoinPage / NodePage
│   └── components/           # Topology / HotStuffTable
├── backend/
│   ├── main.py               # FastAPI 入口与 API 路由
│   ├── socket_handlers.py    # 会话管理与 Socket 事件
│   ├── consensus_engine.py   # 共识核心逻辑
│   ├── consensus_service.py  # 共识服务层
│   ├── robot_agent.py        # 机器人节点行为
│   └── blockchain_sim.db     # SQLite 持久化文件
├── scripts/                  # 离线分析脚本（绘图、建模、标定）
├── thesis/                   # BEng FYP LaTeX 报告
│   ├── main.tex
│   ├── mylit.bib
│   └── figures/
├── docs/history/             # 历史变更记录存档
├── start.bat / start.sh
└── README.md
```

## 可选：离线分析脚本

`scripts/` 目录包含实验数据后处理与绘图工具（`final_analysis.py`、`plot_results.py`、`mathematical_model.py` 等），以及模型标定脚本（`calibrate_model.py`）。  
这部分是辅助研究工具，不是在线系统运行的必需依赖。

## 相关文档

- `PROJECT_STRUCTURE.md`：结构概览
- `启动说明.md`：中文启动说明
- `ANIMATION_DEMO_GUIDE.md`：演示说明
- `MULTI_ROUND_SUPPORT.md`、`REALTIME_ONLY_UPDATE.md`：功能迭代记录

## 许可证

MIT License