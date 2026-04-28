# 项目结构说明

本项目（package.json 中名为 `distributed-hotstuff`）是一个面向教学与演示的分布式共识可视化系统，后端基于 FastAPI + Socket.IO 实现 HotStuff 共识算法，前端基于 Vue 3 + Element Plus 提供主控、加入与节点三个交互页面。早期版本基于 PBFT，因此仓库中仍保留了一批旧的 PBFT 相关文档，命名上请以本文件描述的当前结构为准。

## 目录树

```
distributed-hotstuff/
├── backend/                         # 后端服务（FastAPI + Socket.IO + SQLite）
│   ├── main.py                      # 应用入口：FastAPI 实例、CORS、ASGI 装载、启动钩子
│   ├── state.py                     # 全局状态：sio 实例、sessions、connected_nodes、统计工具
│   ├── models.py                    # Pydantic 数据模型（SessionConfig 等）
│   ├── consensus_engine.py          # HotStuff 纯算法函数（quorum、阶段流转、QC 扩展、SafeNode 等）
│   ├── consensus_service.py         # ConsensusService：封装状态机逻辑，不依赖网络
│   ├── socket_handlers.py           # 所有 Socket.IO 事件处理与消息流程编排
│   ├── robot_agent.py               # 自动化节点代理（自动投票、提案、调度）
│   ├── topology_manager.py          # 拓扑与分组管理、Leader 选择、连接合法性
│   ├── database.py                  # SQLite 持久化（会话快照与历史记录）
│   ├── blockchain_sim.db            # 运行期生成的 SQLite 数据库
│   ├── requirements.txt             # Python 依赖
│   └── __pycache__/                 # 编译缓存
│
├── src/                             # 前端源码（Vue 3）
│   ├── main.js                      # 入口：注册 Pinia、Vue Router、Element Plus、auto-animate
│   ├── App.vue                      # 根组件
│   ├── views/
│   │   ├── HomePage.vue             # 主控页：会话创建、参数配置、二维码生成
│   │   ├── JoinPage.vue             # 加入页：扫码后的节点选择
│   │   └── NodePage.vue             # 节点页：参与共识、查看消息与状态
│   ├── components/
│   │   ├── HotStuffTable.vue        # HotStuff 共识过程表格（前身为 PBFTTable）
│   │   └── Topology.vue             # 网络拓扑可视化
│   └── stores/
│       └── sessionStore.js          # Pinia store：会话/阶段/已连节点等共享状态
│
├── vite.config.js                   # Vite 构建配置
├── package.json                     # 前端依赖与脚本（dev / build / preview）
│
├── start.sh / start.bat             # 一键启动脚本（Linux/macOS、Windows）
├── stop.bat                         # 停止脚本
├── 启动调试.bat                      # 调试模式启动
│
├── 历史与说明文档（约 17 份 .md）       # 详见下文“文档分类”
├── 测试与调试脚本（约 9 份 test_*.py） # 详见下文“测试脚本”
└── test_ui.html                     # 独立的前端联调页面
```

## 后端模块

`main.py` 仅负责装配：构造 FastAPI 实例并配置 CORS，将 `state.sio` 与 FastAPI 一起包装为 ASGI 应用，再通过 `import socket_handlers` 触发事件装饰器注册。`@app.on_event("startup")` 调用 `database.init_db()` 完成 SQLite 初始化，并把磁盘上的会话恢复到内存。运行中处于 `running` 状态的会话因为后台任务无法在重启后继续，因此会被统一回退为 `waiting`。

`state.py` 提供全局可变状态与 Socket.IO 服务器实例，所有模块通过它共享数据，避免循环依赖。同时它实现了消息传达概率（`should_deliver_message`）与消息计数（`count_message_sent`）等贯穿全链路的统计工具。

`consensus_engine.py` 是 HotStuff 共识的纯算法层。`get_quorum_threshold` 给出全局 2f+1 阈值，`get_local_quorum_threshold` 用于双层 HotStuff 的组内阈值，`get_next_phase` 描述阶段流转 `new-view → prepare → pre-commit → commit → decide`，`qc_extends` 与 `check_safe_node` 实现 Safety 条件，`update_node_locked_qc`、`update_node_prepare_qc` 维护节点的 QC 状态。

`consensus_service.py` 在引擎之上封装 `ConsensusService` 类，承担消息校验、阈值统计、QC 生成、复杂度计算等状态机职责。它显式声明不依赖 Socket.IO，也不做持久化，仅读写传入的 session 对象，便于测试。

`socket_handlers.py` 是网络与业务层的胶水：注册所有 `@sio.event` 处理器，编排消息广播、阶段切换与持久化触发，并把机器人的自动化能力以回调方式委派给 `robot_agent`。

`robot_agent.py` 通过 `RobotAgent` 类实现自动节点的纯逻辑（生成提案与投票、状态重置），并提供与网络层协作的异步函数，对自动化节点的发送与调度负责。

`topology_manager.py` 管理拓扑与分组：HotStuff 的 Leader Rotation 通过 `view % n` 选出当前主，`_build_groups` 把 n 个节点按 branch_count 切成尽量均匀的若干组，并提供 `is_connection_allowed` 与 `get_topology_info` 给上层使用。

`database.py` 封装 SQLite 访问。会话快照与共识历史分表存储，连接默认开启外键约束，库文件默认落在 backend 目录下的 `blockchain_sim.db`。

## 前端模块

`main.js` 装配整个 Vue 应用：创建 router 注册三条路由（`/`、`/join/:sessionId`、`/node/:sessionId/:nodeId`），全局注册 Element Plus 图标，挂载 Pinia、Element Plus 与 `@formkit/auto-animate` 全局指令。

`views/` 下的三个页面对应三类用户操作：`HomePage` 完成会话创建与二维码生成，`JoinPage` 处理扫码后的节点选择与权限说明，`NodePage` 是真正的共识参与界面，提供消息收发、阶段进度与拓扑可视化。

`components/HotStuffTable.vue` 渲染 HotStuff 共识过程的状态表格，是节点页的核心信息面板，文件名沿用了重构前 `PBFTTable` 的语义。`components/Topology.vue` 负责网络拓扑的图形化展示。

`stores/sessionStore.js` 是 Pinia store，把 `sessionId`、`sessionConfig`、`connectedNodes`、`currentPhase`、`currentView`、`leaderId` 等页面间共享的会话状态从 `HomePage` 与 `NodePage` 中解耦出来，并以 `sessionInfo` 等 getter 提供视图组合。

## 数据流

主控用户在 HomePage 通过 HTTP 接口创建会话，得到二维码与各节点链接。参与用户扫码进入 JoinPage 选择节点，再跳转到 NodePage 通过 Socket.IO 建立长连，发送/接收 HotStuff 各阶段消息，由 `socket_handlers` 调度 `consensus_service` 与 `robot_agent` 推进共识，所有节点状态、阶段切换与历史记录通过 `database` 异步持久化到 SQLite。

## 技术栈

前端依赖（来自 package.json）包含 Vue 3、Vue Router 4、Pinia 3、Element Plus 2 与配套图标库、ECharts 6 与 vue-echarts、Socket.IO Client 4、qrcode 与 qrcode.vue、@formkit/auto-animate、axios，构建工具为 Vite 6。后端依赖见 `backend/requirements.txt`，核心是 FastAPI、python-socketio、Pydantic、Uvicorn 与标准库 `sqlite3`。

## 共识与容错

HotStuff 在 n 节点下最多容忍 f = ⌊(n-1)/3⌋ 个故障节点，全局 quorum 为 2f+1。Leader 通过 `view % n` 轮换。Safety 条件由 `qc_extends` 与 `check_safe_node` 共同保障，节点会在 prepare 阶段更新 `prepareQC`、在 pre-commit 阶段更新 `lockedQC`。系统支持模拟拜占庭节点（恶意提议、消息篡改）、消息丢包（按 `messageDeliveryRate` 概率丢弃）以及双层 HotStuff（按组内阈值聚合）。

## 启动方式

开发环境下，可在仓库根目录执行 `start.sh`（Linux/macOS）或 `start.bat`（Windows）一键启动后端与前端开发服务器；也可分别在 `backend/` 下运行 `python main.py`（或通过 uvicorn 暴露 `main:socket_app`），并在仓库根目录运行 `npm run dev`。生产部署时，先 `npm run build` 产出静态资源，再 `pip install -r backend/requirements.txt` 部署后端。

## 文档分类

仓库根目录积累了较多过程性文档，可按主题分为四类。共识与攻击模拟相关的有 `ATTACK_METHODS_GUIDE.md`、`BAD_NODE_GUIDE.md`、`REALISTIC_ATTACK_PROPOSAL.md`、`MULTI_ROUND_SUPPORT.md`、`PROPOSER_FIX.md`。UI 与动画相关的有 `ANIMATION_DEMO_GUIDE.md`、`ANIMATION_UPDATE_SUMMARY.md`、`UI_IMPROVEMENT_PLANS.md`、`REALTIME_ONLY_UPDATE.md`、`CUSTOM_MESSAGE_REMOVAL.md`。Bug 修复记录有 `BUG_FIX_404.md`、`FIX_HISTORY_ROUNDS.md`、`FIX_MESSAGE_DUPLICATION.md`、`STATS_FIX.md`。运行与诊断类有 `DIAGNOSTICS.md`、`demo.md`、`启动说明.md`，以及本文件 `PROJECT_STRUCTURE.md`。这些文档以变更日志的形式存在，不一定与最新代码完全一致，使用时建议结合 git 历史核对。

## 测试脚本

根目录的 `test_backend.py`、`test_byzantine.py`、`test_message_delivery.py`、`test_proposal_content.py`、`test_proposer_fix.py`、`test_rounds_check.py`、`test_socket.py`、`test_stats_fix.py`、`simple_test.py` 是迭代过程中沉淀的调试脚本，主要用于针对性复现问题或验证修复效果，并非完整的自动化测试套件。`test_ui.html` 是用于前端联调的独立页面。

## 与旧版本的差异

相对于早期 PBFT 版本，当前结构的主要变化在于：共识算法切换为 HotStuff，因此组件 `PBFTTable.vue` 改名为 `HotStuffTable.vue`，并新增 `Topology.vue`；前端引入 Pinia 状态管理，新增 `stores/sessionStore.js`；后端从单一的 `main.py` 拆分为 `main / state / consensus_engine / consensus_service / socket_handlers / robot_agent / topology_manager / database / models` 九个模块，并增加了 SQLite 持久化层。
