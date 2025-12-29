from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import socketio
import uuid
import random
import asyncio
from datetime import datetime
import json

# 创建FastAPI应用
app = FastAPI(title="分布式PBFT共识系统", version="1.0.0")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建Socket.IO服务器
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*"
)

# 创建ASGI应用
socket_app = socketio.ASGIApp(sio, app)

# 数据模型
class SessionConfig(BaseModel):
    nodeCount: int
    faultyNodes: int
    robotNodes: int  # 机器人节点数量
    topology: str
    branchCount: Optional[int] = 2
    proposalValue: int
    proposalContent: Optional[str] = ""
    maliciousProposer: bool
    allowTampering: bool
    messageDeliveryRate: int = 100

class SessionInfo(BaseModel):
    sessionId: str
    nodeCount: int
    faultyNodes: int
    topology: str
    proposalValue: int
    status: str
    createdAt: str

# 全局状态管理
sessions: Dict[str, Dict[str, Any]] = {}
connected_nodes: Dict[str, List[int]] = {}
node_sockets: Dict[str, Dict[int, str]] = {}

# 会话管理
def create_session(config: SessionConfig) -> SessionInfo:
    session_id = str(uuid.uuid4())
    
    print(f"创建会话 - 原始配置:", config.dict())
    print(f"提议内容检查 - 创建时:", {
        'proposalContent': config.proposalContent,
        'hasProposalContent': config.proposalContent and config.proposalContent.strip(),
        'proposalValue': config.proposalValue
    })
    
    session = {
        "config": config.dict(),
        "status": "waiting",
        "phase": "waiting",
        "phase_step": 0,
        "current_view": 0,   # 当前视图编号（HotStuff，View 即时钟）
        "leader_id": 0,      # 当前视图的Leader ID
        "connected_nodes": [],
        "robot_nodes": [],  # 机器人节点列表
        "human_nodes": [],  # 人类节点列表（拜占庭节点）
        "robot_node_states": {},  # 机器人节点的状态（记录收到的消息）
        "timeout_task": None,  # 超时任务
        "messages": {
            "pre_prepare": [],
            "prepare": [],
            "commit": [],
            "vote": [],
            "qc": [],
            "new_view": []  # NEW-VIEW 消息
        },
        "node_states": {},  # 每个节点的持久化状态 {node_id: {lockedQC, prepareQC, currentView}}
        "pending_votes": {},  # {(view, phase, value): set(voter_ids)}
        "pending_new_views": {},  # {(view): {node_id: new_view_msg}} Leader 收集的 NEW-VIEW 消息
        "message_buffer": {},  # {node_id: {view: [messages]}} 未来视图的消息缓冲池
        "network_stats": {    # 通信复杂度统计
            "total_messages_sent": 0,  # 本轮产生的总网络包数量
            "phases_count": 0          # 经历的阶段数（HotStuff阶段流转次数）
        },
        "consensus_result": None,
        "consensus_history": [],  # 共识历史记录
        "created_at": datetime.now().isoformat()
    }
    
    # 初始化每个节点的持久化状态（HotStuff Safety 要求）
    n = config.nodeCount
    for node_id in range(n):
        session["node_states"][node_id] = {
            "lockedQC": None,      # 最高锁定的 QC (用于 SafeNode 检查)
            "prepareQC": None,     # 最高准备的 QC (用于 New-View 选择 HighQC)
            "currentView": 0,      # 节点当前视图（用于消息验证）
            "highQC": None         # 用于 New-View 的最高 QC
        }
    session["leader_id"] = session["current_view"] % config.nodeCount
    
    sessions[session_id] = session
    connected_nodes[session_id] = []
    node_sockets[session_id] = {}
    
    # 创建机器人节点并立即开始共识
    asyncio.create_task(create_robot_nodes_and_start(session_id, config.robotNodes))
    
    return {
        "sessionId": session_id,
        "config": {
            "nodeCount": config.nodeCount,
            "faultyNodes": config.faultyNodes,
            "robotNodes": config.robotNodes,
            "topology": config.topology,
            "branchCount": config.branchCount,
            "proposalValue": config.proposalValue,
            "proposalContent": config.proposalContent,
            "maliciousProposer": config.maliciousProposer,
            "allowTampering": config.allowTampering,
            "messageDeliveryRate": config.messageDeliveryRate
        },
        "status": "waiting",
        "createdAt": session["created_at"]
    }

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    return sessions.get(session_id)

def get_current_leader(session: Dict[str, Any], view: Optional[int] = None) -> int:
    """返回指定视图的Leader（HotStuff Leader Rotation: view % n）"""
    if view is None:
        view = session["current_view"]
    n = session["config"]["nodeCount"]
    return view % n

def get_quorum_threshold(session: Dict[str, Any]) -> int:
    """HotStuff 需要 2f+1 票"""
    n = session["config"]["nodeCount"]
    f = (n - 1) // 3
    return 2 * f + 1

def get_next_phase(phase: str) -> str:
    """HotStuff 阶段流转"""
    mapping = {
        "new-view": "prepare",
        "prepare": "pre-commit",
        "pre-commit": "commit",
        "commit": "decide",
        "decide": "decide"
    }
    return mapping.get(phase, "prepare")

def qc_extends(qc1: Optional[Dict], qc2: Optional[Dict]) -> bool:
    """检查 qc1 是否扩展自 qc2（HotStuff 的 Safety 条件：extends 关系）"""
    if qc2 is None:
        return True  # 如果 lockedQC 为空，任何 QC 都满足条件
    if qc1 is None:
        return False
    
    # 简化实现：检查 view 和 value 的继承关系
    # 在实际 HotStuff 中，这需要检查区块链的父节点关系
    # 这里我们简化为：如果 qc1.view > qc2.view 且 value 相同，则视为扩展
    view1 = qc1.get("view", -1)
    view2 = qc2.get("view", -1)
    value1 = qc1.get("value")
    value2 = qc2.get("value")
    
    # 如果 qc1 的 view 更高且 value 相同，则视为扩展关系
    return view1 > view2 and value1 == value2

def check_safe_node(session: Dict[str, Any], node_id: int, proposal_view: int, proposal_value: int, proposal_qc: Optional[Dict]) -> bool:
    """
    HotStuff SafeNode 谓词检查（Safety 的核心机制）
    
    条件：msg.view > lockedQC.view OR msg.extends(lockedQC)
    
    参数:
        session: 会话数据
        node_id: 节点ID
        proposal_view: 提案的视图号
        proposal_value: 提案的值
        proposal_qc: 提案携带的 QC（可选）
    
    返回:
        bool: 如果通过 SafeNode 检查返回 True，否则返回 False
    """
    node_state = session["node_states"].get(node_id, {})
    lockedQC = node_state.get("lockedQC")
    
    # 条件1: proposal_view > lockedQC.view (Liveness/Freshness)
    if lockedQC is None:
        # 如果没有锁定QC，允许投票（首次提案）
        print(f"节点 {node_id}: SafeNode 检查通过（无 lockedQC）")
        return True
    
    locked_view = lockedQC.get("view", -1)
    if proposal_view > locked_view:
        print(f"节点 {node_id}: SafeNode 检查通过（proposal_view {proposal_view} > lockedQC.view {locked_view}）")
        return True
    
    # 条件2: proposal.extends(lockedQC) (Safety)
    if proposal_qc:
        if qc_extends(proposal_qc, lockedQC):
            print(f"节点 {node_id}: SafeNode 检查通过（proposal QC 扩展自 lockedQC）")
            return True
        else:
            print(f"节点 {node_id}: SafeNode 检查失败（proposal QC 不扩展自 lockedQC）")
            return False
    
    # 如果 proposal_qc 为空但 proposal_value 与 lockedQC.value 相同，也视为扩展
    locked_value = lockedQC.get("value")
    if proposal_value == locked_value and proposal_view >= locked_view:
        print(f"节点 {node_id}: SafeNode 检查通过（proposal value 与 lockedQC value 相同）")
        return True
    
    # 不满足任何条件，拒绝提案
    print(f"节点 {node_id}: SafeNode 检查失败（proposal_view {proposal_view} <= lockedQC.view {locked_view} 且不扩展）")
    return False

def update_node_locked_qc(session: Dict[str, Any], node_id: int, qc: Dict):
    """
    更新节点的 lockedQC（在收到 CommitQC 时调用）
    
    参数:
        session: 会话数据
        node_id: 节点ID
        qc: 新的 QC（必须是 Commit 阶段的 QC）
    """
    node_state = session["node_states"].get(node_id, {})
    current_locked = node_state.get("lockedQC")
    
    qc_view = qc.get("view", -1)
    if current_locked is None or qc_view > current_locked.get("view", -1):
        node_state["lockedQC"] = qc.copy()
        print(f"节点 {node_id}: 更新 lockedQC 到 view {qc_view}")
    else:
        print(f"节点 {node_id}: 忽略旧的 QC（view {qc_view} <= current lockedQC.view {current_locked.get('view', -1)}）")

def update_node_prepare_qc(session: Dict[str, Any], node_id: int, qc: Dict):
    """
    更新节点的 prepareQC（在收到任何阶段的 QC 时调用，用于 New-View 选择 HighQC）
    
    参数:
        session: 会话数据
        node_id: 节点ID
        qc: 新的 QC
    """
    node_state = session["node_states"].get(node_id, {})
    current_prepare = node_state.get("prepareQC")
    
    qc_view = qc.get("view", -1)
    if current_prepare is None or qc_view > current_prepare.get("view", -1):
        node_state["prepareQC"] = qc.copy()
        node_state["highQC"] = qc.copy()  # HighQC 就是最高的 prepareQC
        print(f"节点 {node_id}: 更新 prepareQC/highQC 到 view {qc_view}")

def is_connection_allowed(i: int, j: int, n: int, topology: str, n_value: int) -> bool:
    """
    检查两个节点之间是否允许连接（仅用于历史记录展示，不影响实际共识逻辑）
    
    注意：HotStuff 协议要求星型拓扑（Leader <-> All Replicas）
    实际的共识逻辑中，所有通信都是星型的（通过 get_current_leader 强制）
    此函数仅用于前端历史记录的拓扑可视化
    """
    if i == j:
        return False
    
    # HotStuff 强制星型拓扑：Leader 可以与所有节点通信，非 Leader 只能与 Leader 通信
    # 为了兼容前端，这里仍然检查配置的 topology，但实际逻辑中已强制星型
    # 如果配置不是 star，在历史记录中也会按 star 方式显示（Leader <-> All）
    leader_id = get_current_leader({"config": {"nodeCount": n}, "current_view": 0}, 0)  # 假设 view=0，仅用于判断
    # 在实际使用中，应该根据消息的 view 来确定 leader
    # 这里简化处理，只检查是否是 Leader 与其他节点的连接
    if topology == "star" or True:  # 强制星型（HotStuff 要求）
        return True  # 在星型拓扑中，所有节点都可以与 Leader 通信（展示用）
    
    # 以下代码仅作为参考，实际不会被使用（因为上面已经 return True）
    if topology == "full":
        return True
    elif topology == "ring":
        return j == (i + 1) % n or j == (i - 1) % n
    elif topology == "tree":
        parent = (j - 1) // n_value
        return i == parent and j < n
    return False

def is_honest(node_id: int, n: int, m: int, faulty_proposer: bool) -> bool:
    """判断节点是否为诚实节点"""
    if m == 0:
        return True
    if faulty_proposer:
        if node_id == 0:
            return False
        return node_id <= n - m
    else:
        if node_id == 0:
            return True
        return node_id < n - m

def should_deliver_message(session_id: str) -> bool:
    """根据消息传达概率决定是否发送消息"""
    session = get_session(session_id)
    if not session:
        return True
    
    delivery_rate = session["config"].get("messageDeliveryRate", 100)
    if delivery_rate >= 100:
        return True
    
    # 生成随机数，如果小于传达概率则发送消息
    return random.random() * 100 < delivery_rate

def count_message_sent(session_id: str, is_broadcast: bool = True, target_count: Optional[int] = None):
    """统计发送的消息数量
    
    参数:
        session_id: 会话ID
        is_broadcast: 是否为广播消息（True=广播，False=单播）
        target_count: 目标节点数量（如果为None，则使用总节点数-1）
    """
    session = get_session(session_id)
    if not session:
        return
    
    # 确保network_stats存在
    if "network_stats" not in session:
        session["network_stats"] = {
            "total_messages_sent": 0,
            "phases_count": 0
        }
    
    if is_broadcast:
        # 广播消息：发送给所有其他节点（N-1）
        if target_count is None:
            n = session["config"]["nodeCount"]
            message_count = max(n - 1, 0)
        else:
            message_count = max(int(target_count), 0)
    else:
        # 单播消息：只发送给一个节点
        message_count = 1
    
    session["network_stats"]["total_messages_sent"] += message_count

# HTTP路由
@app.post("/api/sessions")
async def create_consensus_session(config: SessionConfig):
    """创建新的共识会话"""
    try:
        session_info = create_session(config)
        return session_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/{session_id}")
async def get_session_info(session_id: str):
    """获取会话信息"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 创建一个可序列化的副本，排除不可序列化的字段
    session_copy = {}
    for key, value in session.items():
        if key == "timeout_task":
            # 跳过 asyncio 任务对象
            continue
        session_copy[key] = value
    
    return session_copy

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话并停止所有相关进程"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 停止会话
    session["status"] = "stopped"
    
    # 清理会话数据
    if session_id in sessions:
        del sessions[session_id]
    if session_id in connected_nodes:
        del connected_nodes[session_id]
    if session_id in node_sockets:
        del node_sockets[session_id]
    
    print(f"会话 {session_id} 已被删除并停止")
    
    return {"message": "会话已删除"}

@app.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """获取会话状态"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return {
        "sessionId": session_id,
        "status": session["status"],
        "phase": session["phase"],
        "connectedNodes": len(connected_nodes.get(session_id, [])),
        "totalNodes": session["config"]["nodeCount"]
    }

@app.post("/api/sessions/{session_id}/assign-node")
async def assign_node(session_id: str):
    """自动分配节点"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    # 获取已连接的节点
    connected = connected_nodes.get(session_id, [])
    total_nodes = session["config"]["nodeCount"]
    
    # 找到第一个可用的节点
    available_node = None
    for i in range(total_nodes):
        if i not in connected:
            available_node = i
            break
    
    if available_node is None:
        raise HTTPException(status_code=409, detail="所有节点已被占用")
    
    return {
        "nodeId": available_node,
        "sessionId": session_id,
        "role": "提议者" if available_node == 0 else "验证者",
        "totalNodes": total_nodes,
        "connectedNodes": len(connected)
    }

@app.get("/api/sessions/{session_id}/connected-nodes")
async def get_connected_nodes(session_id: str):
    """获取已连接的节点列表"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    connected = connected_nodes.get(session_id, [])
    return {
        "sessionId": session_id,
        "connectedNodes": connected,
        "totalNodes": session["config"]["nodeCount"]
    }

@app.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str, round: Optional[int] = None):
    """获取会话的真实消息历史，适配 HotStuff 表格和动画"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    config = session["config"]
    messages = session["messages"]
    n = config["nodeCount"]
    topology = config["topology"]
    n_value = config.get("branchCount", 2)
    
    # 1. 确定轮次范围
    if round is None:
        # 获取所有存在的轮次
        all_rounds = set()
        for key in ["pre_prepare", "vote", "qc"]:
            for msg in messages.get(key, []):
                if "round" in msg:
                    all_rounds.add(msg["round"])
        target_rounds = sorted(list(all_rounds))
        current_round = session.get("current_round", 1)
        return {
            "rounds": target_rounds,
            "currentRound": current_round,
            "totalRounds": len(target_rounds)
        }

    # 2. 准备数据容器
    table_messages: List[Dict[str, Any]] = []      # 表格用（合并广播，含phase）
    animation_sequence: List[List[Dict[str, Any]]] = []  # 动画用（拆分广播，按步骤）
    
    # 辅助函数：按轮次过滤
    def get_msgs(key, r):
        return [m for m in messages.get(key, []) if m.get("round") == r]

    round_pre_prepare = get_msgs("pre_prepare", round)
    round_votes = get_msgs("vote", round)
    round_qc = get_msgs("qc", round)

    # === 构建 HotStuff 7步 流程 ===

    # Step 1: Proposal (Leader -> All) [Phase: Prepare]
    step1_anim: List[Dict[str, Any]] = []
    for msg in round_pre_prepare:
        # 表格数据：保留广播，添加 phase
        table_msg = msg.copy()
        table_msg["phase"] = "prepare" 
        table_msg["type"] = "proposal"
        table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
        table_messages.append(table_msg)

        # 动画数据：拆分广播
        src = msg["from"]
        value = msg.get("value")
        if msg.get("to") == "all":
            for dst in range(n):
                if dst != src and is_connection_allowed(src, dst, n, topology, n_value):
                    step1_anim.append({"src": src, "dst": dst, "value": value, "type": "proposal"})
        else:
            step1_anim.append({"src": src, "dst": msg.get("to"), "value": value, "type": "proposal"})
    animation_sequence.append(step1_anim)

    # Step 2: Prepare Vote (All -> Leader) [Phase: Prepare]
    step2_msgs: List[Dict[str, Any]] = []
    for msg in round_votes:
        if msg.get("phase") == "prepare":
            m = {"src": msg["from"], "dst": msg["to"], "value": msg.get("value"), "type": "vote", "phase": "prepare"}
            step2_msgs.append(m)
            table_messages.append(m)
    animation_sequence.append(step2_msgs)

    # Step 3: Pre-Commit QC (Leader -> All) [Phase: Pre-Commit]
    step3_anim: List[Dict[str, Any]] = []
    for msg in round_qc:
        if msg.get("phase") == "prepare":  # Prepare QC 开启 Pre-Commit 阶段
            # 表格数据
            table_msg = msg.copy()
            table_msg["phase"] = "pre-commit"
            table_msg["type"] = "qc"
            table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
            table_messages.append(table_msg)
            
            # 动画数据
            src = msg["from"]
            value = msg.get("qc", {}).get("value")
            if msg.get("to") == "all":
                for dst in range(n):
                    if dst != src and is_connection_allowed(src, dst, n, topology, n_value):
                        step3_anim.append({"src": src, "dst": dst, "value": value, "type": "qc"})
    animation_sequence.append(step3_anim)

    # Step 4: Pre-Commit Vote (All -> Leader) [Phase: Pre-Commit]
    step4_msgs: List[Dict[str, Any]] = []
    for msg in round_votes:
        if msg.get("phase") == "pre-commit": 
            m = {"src": msg["from"], "dst": msg["to"], "value": msg.get("value"), "type": "vote", "phase": "pre-commit"}
            step4_msgs.append(m)
            table_messages.append(m)
    animation_sequence.append(step4_msgs)

    # Step 5: Commit QC (Leader -> All) [Phase: Commit]
    step5_anim: List[Dict[str, Any]] = []
    for msg in round_qc:
        if msg.get("phase") == "pre-commit":  # Pre-Commit QC 开启 Commit 阶段
            # 表格数据
            table_msg = msg.copy()
            table_msg["phase"] = "commit"
            table_msg["type"] = "qc"
            table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
            table_messages.append(table_msg)

            # 动画数据
            src = msg["from"]
            value = msg.get("qc", {}).get("value")
            if msg.get("to") == "all":
                for dst in range(n):
                    if dst != src and is_connection_allowed(src, dst, n, topology, n_value):
                        step5_anim.append({"src": src, "dst": dst, "value": value, "type": "qc"})
    animation_sequence.append(step5_anim)

    # Step 6: Commit Vote (All -> Leader) [Phase: Commit]
    step6_msgs: List[Dict[str, Any]] = []
    for msg in round_votes:
        if msg.get("phase") == "commit":
            m = {"src": msg["from"], "dst": msg["to"], "value": msg.get("value"), "type": "vote", "phase": "commit"}
            step6_msgs.append(m)
            table_messages.append(m)
    animation_sequence.append(step6_msgs)

    # Step 7: Decide QC (Leader -> All) [Phase: Decide]
    step7_anim: List[Dict[str, Any]] = []
    for msg in round_qc:
        if msg.get("phase") == "commit":  # Commit QC 开启 Decide 阶段
            # 表格数据
            table_msg = msg.copy()
            table_msg["phase"] = "decide"
            table_msg["type"] = "qc"
            table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
            table_messages.append(table_msg)

            # 动画数据
            src = msg["from"]
            value = msg.get("qc", {}).get("value")
            if msg.get("to") == "all":
                for dst in range(n):
                    if dst != src and is_connection_allowed(src, dst, n, topology, n_value):
                        step7_anim.append({"src": src, "dst": dst, "value": value, "type": "qc"})
    animation_sequence.append(step7_anim)

    # 获取共识结果文本
    round_consensus = "共识进行中..."
    for history in session.get("consensus_history", []):
        if history.get("round") == round:
            round_consensus = f"{history.get('status', '未知')}: {history.get('description', '')}"
            break

    return {
        "round": round,
        "leaderId": (round - 1) % config["nodeCount"],
        "messages": table_messages,               # 表格数据（含phase，未拆分广播）
        "animation_sequence": animation_sequence, # 动画数据（7步序列，拆分广播）
        "consensus": round_consensus,
        "nodeCount": config["nodeCount"],
        "topology": config["topology"],
        "proposalValue": config["proposalValue"]
    }

# Socket.IO事件处理
@sio.event
async def connect(sid, environ, auth):
    """客户端连接事件"""
    print(f"客户端连接: {sid}")
    
    # 从查询参数获取会话和节点信息
    query = environ.get('QUERY_STRING', '')
    params = dict(item.split('=') for item in query.split('&') if '=' in item)
    
    session_id = params.get('sessionId')
    node_id = int(params.get('nodeId', 0))
    
    if session_id and session_id in sessions:
        # 存储节点连接信息
        if session_id not in node_sockets:
            node_sockets[session_id] = {}
        node_sockets[session_id][node_id] = sid
        
        # 添加到已连接节点列表
        if session_id not in connected_nodes:
            connected_nodes[session_id] = []
        if node_id not in connected_nodes[session_id]:
            connected_nodes[session_id].append(node_id)
            
            # 标记人类节点为拜占庭节点
            session = sessions[session_id]
            if node_id not in session["robot_nodes"]:
                session["human_nodes"].append(node_id)
                print(f"人类节点 {node_id} 已连接（拜占庭节点）")
            else:
                print(f"机器人节点 {node_id} 已重新连接")
        
        session = sessions[session_id]
        
        # 发送会话配置
        config = session["config"]
        print(f"发送会话配置给节点 {node_id}:", config)
        print(f"提议内容检查 - 后端:", {
            'proposalContent': config.get('proposalContent'),
            'hasProposalContent': config.get('proposalContent') and config.get('proposalContent').strip(),
            'proposalValue': config.get('proposalValue')
        })
        await sio.emit('session_config', config, room=sid)
        
        # 人类节点进入时，不参加当前轮次的共识
        # 只发送会话配置，不发送当前轮次信息和历史消息
        print(f"人类节点 {node_id} 进入，等待下一轮共识开始")
        
        # 将节点加入会话房间
        await sio.enter_room(sid, session_id)
        
        # 广播连接状态
        await sio.emit('connected_nodes', connected_nodes[session_id], room=session_id)
        
        print(f"节点 {node_id} 加入会话 {session_id}")
        
        # 检查是否可以开始共识
        await check_and_start_consensus(session_id)

@sio.event
async def disconnect(sid):
    """客户端断开连接事件"""
    print(f"客户端断开连接: {sid}")
    
    # 查找并移除节点连接
    for session_id, nodes in node_sockets.items():
        for node_id, node_sid in nodes.items():
            if node_sid == sid:
                del nodes[node_id]
                if node_id in connected_nodes.get(session_id, []):
                    connected_nodes[session_id].remove(node_id)
                
                # 广播更新
                await sio.emit('connected_nodes', connected_nodes[session_id], room=session_id)
                print(f"节点 {node_id} 离开会话 {session_id}")
                break

@sio.event
async def send_prepare(sid, data):
    """处理准备消息"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    value = data.get('value')
    
    session = get_session(session_id)
    if not session:
        return
    
    leader_id = get_current_leader(session)
    leader_sid = node_sockets.get(session_id, {}).get(leader_id)
    
    # 构造投票（VOTE）消息，只发送给当前Leader
    vote_message = {
        "from": node_id,
        "to": leader_id,
        "type": "vote",
        "value": value,
        "phase": "prepare",
        "view": session["current_view"],
        "round": session["current_view"],  # 兼容前端：round 与 view 相同（HotStuff 不使用 round）
        "qc": data.get("qc"),
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "byzantine": data.get("byzantine", False)
    }
    
    session["messages"]["vote"].append(vote_message)
    
    # 单播给Leader（不广播）
    if leader_sid:
        count_message_sent(session_id, is_broadcast=False)
        await sio.emit('message_received', vote_message, room=leader_sid)
        print(f"节点 {node_id} 向 Leader {leader_id} 发送 VOTE(prepare)")
    else:
        print(f"Leader {leader_id} 不在线，缓存 VOTE")
    
    # 直接在后端处理投票累积
    await handle_vote(session_id, vote_message)

@sio.event
async def send_commit(sid, data):
    """处理提交消息"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    value = data.get('value')
    
    session = get_session(session_id)
    if not session:
        return
    
    leader_id = get_current_leader(session)
    leader_sid = node_sockets.get(session_id, {}).get(leader_id)
    
    # 构造投票（VOTE）消息，只发送给当前Leader
    vote_message = {
        "from": node_id,
        "to": leader_id,
        "type": "vote",
        "value": value,
        "phase": "commit",
        "view": session["current_view"],
        "round": session["current_view"],  # 兼容前端：round 与 view 相同（HotStuff 不使用 round）
        "qc": data.get("qc"),
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "byzantine": data.get("byzantine", False)
    }
    
    session["messages"]["vote"].append(vote_message)
    
    # 单播给Leader（不广播）
    if leader_sid:
        count_message_sent(session_id, is_broadcast=False)
        await sio.emit('message_received', vote_message, room=leader_sid)
        print(f"节点 {node_id} 向 Leader {leader_id} 发送 VOTE(commit)")
    else:
        print(f"Leader {leader_id} 不在线，缓存 VOTE")
    
    # 直接在后端处理投票累积
    await handle_vote(session_id, vote_message)
    

@sio.event
async def send_message(sid, data):
    """处理通用消息（已移除自定义消息功能）"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    message_type = data.get('type')
    value = data.get('value')
    target = data.get('target')
    
    session = get_session(session_id)
    if not session:
        return
    
    # 记录消息
    message = {
        "from": node_id,
        "to": target,
        "type": message_type,
        "value": value,
        "phase": session.get("phase", "waiting"),
        "view": session.get("current_view", 0),  # HotStuff视图
        "round": session.get("current_round", 1),  # 当前轮次（用于历史过滤）
        "qc": data.get("qc"),                    # Quorum Certificate
        "timestamp": datetime.now().isoformat(),
        "tampered": False
    }
    
    # 根据消息类型存储到相应的消息列表
    if message_type == "prepare":
        session["messages"]["prepare"].append(message)
    elif message_type == "commit":
        session["messages"]["commit"].append(message)
    elif message_type == "vote":
        # HotStuff 投票消息存入 vote 列表
        session["messages"]["vote"].append(message)
    else:
        # 其他类型消息
        if "other" not in session["messages"]:
            session["messages"]["other"] = []
        session["messages"]["other"].append(message)
    
    # 根据消息类型决定发送范围（HotStuff：非投票消息由Leader广播，投票单播给Leader）
    if message_type == "vote":
        leader_id = get_current_leader(session)
        leader_sid = node_sockets.get(session_id, {}).get(leader_id)
        if leader_sid:
            count_message_sent(session_id, is_broadcast=False)
            await sio.emit('message_received', message, room=leader_sid)
            print(f"节点 {node_id} 向 Leader {leader_id} 发送 VOTE")
        else:
            print(f"Leader {leader_id} 不在线，缓存 VOTE")
        await handle_vote(session_id, message)
    else:
        # 其他消息默认广播给所有节点
        if should_deliver_message(session_id):
            await sio.emit('message_received', message, room=session_id)
            print(f"节点 {node_id} 的消息已发送 (传达概率: {session['config'].get('messageDeliveryRate', 100)}%)")
        else:
            print(f"节点 {node_id} 的消息被丢弃 (传达概率: {session['config'].get('messageDeliveryRate', 100)}%)")
    

async def trigger_robot_votes(session_id: str, view: int, phase: str, value: int):
    """当进入新阶段时，触发机器人节点发送投票（HotStuff 多阶段自动推进）"""
    print(f"触发机器人自动投票: session={session_id}, view={view}, phase={phase}")
    # 模拟处理延迟，给前端一点时间展示 QC 广播动画
    await asyncio.sleep(2.0)

    session = get_session(session_id)
    if not session:
        return

    # 如果视图已经变化，则不再对旧视图发送投票，避免乱序
    if session.get("current_view") != view:
        print(f"视图已从 {view} 切换为 {session.get('current_view')}，取消本次自动投票")
        return

    config = session["config"]
    leader_id = get_current_leader(session)

    # Decide 阶段不需要再投票，直接结束共识
    if phase == "decide":
        print(f"进入 Decide 阶段，直接完成共识: view={view}")
        await finalize_consensus(session_id, "共识成功", f"View {view} 达成共识")
        return

    # 遍历机器人节点，向 Leader 发送下一阶段投票（pre-commit / commit）
    for robot_id in session.get("robot_nodes", []):
        if robot_id == leader_id:
            # Leader 一般不再给自己单独发 vote 消息
            continue

        vote_msg: Dict[str, Any] = {
            "from": robot_id,
            "to": leader_id,
            "type": "vote",
            "value": value,
            "phase": phase,              # 此处为新的阶段：pre-commit / commit
            "view": view,
            "round": view,  # 兼容前端：round 与 view 相同（HotStuff 不使用 round）
            "timestamp": datetime.now().isoformat(),
            "tampered": False,
            "isRobot": True
        }

        # 写入会话消息历史
        session["messages"]["vote"].append(vote_msg)

        # 发送给 Leader 对应的 socket，让前端能画出 All -> Leader 的投票动画
        leader_sid = node_sockets.get(session_id, {}).get(leader_id)
        if leader_sid:
            count_message_sent(session_id, is_broadcast=False)
            await sio.emit("message_received", vote_msg, room=leader_sid)

        # 交给 HotStuff Leader 聚合逻辑处理
        await handle_vote(session_id, vote_msg)


async def handle_proposal_message(session_id: str, proposal_msg: Dict[str, Any], node_id: int) -> bool:
    """
    处理 Replica 节点收到的 Proposal 消息（HotStuff PRE-PREPARE）
    
    必须通过 SafeNode 谓词检查才能发送 Vote
    
    参数:
        session_id: 会话ID
        proposal_msg: Proposal 消息
        node_id: 接收消息的节点ID
    
    返回:
        bool: 如果通过 SafeNode 检查并发送了 Vote 返回 True，否则返回 False
    """
    session = get_session(session_id)
    if not session:
        return False
    
    proposal_view = proposal_msg.get("view", -1)
    proposal_value = proposal_msg.get("value")
    proposal_qc = proposal_msg.get("qc")
    proposer_id = proposal_msg.get("from")
    
    # 验证消息来自当前视图的 Leader（HotStuff 星型拓扑要求）
    leader_id = get_current_leader(session, proposal_view)
    if proposer_id != leader_id:
        print(f"节点 {node_id}: 拒绝 Proposal（来自非 Leader {proposer_id}，当前 Leader 是 {leader_id}）")
        return False
    
    # HotStuff SafeNode 谓词检查（Safety 的核心机制）
    if not check_safe_node(session, node_id, proposal_view, proposal_value, proposal_qc):
        print(f"节点 {node_id}: SafeNode 检查失败，拒绝 Proposal（View {proposal_view}）")
        return False
    
    # 通过 SafeNode 检查，节点可以发送 Vote
    print(f"节点 {node_id}: SafeNode 检查通过，将发送 Vote（View {proposal_view}, Value {proposal_value}）")
    return True

async def handle_qc_message(session_id: str, qc_msg: Dict[str, Any], node_id: int):
    """
    处理节点收到的 QC 消息（HotStuff 阶段推进）
    
    当收到 Commit 阶段的 QC 时，更新节点的 lockedQC
    收到任何阶段的 QC 时，更新节点的 prepareQC（用于 New-View）
    
    参数:
        session_id: 会话ID
        qc_msg: QC 消息
        node_id: 接收消息的节点ID
    """
    session = get_session(session_id)
    if not session:
        return
    
    qc = qc_msg.get("qc", {})
    qc_phase = qc.get("phase", "")
    qc_view = qc.get("view", -1)
    
    # 更新 prepareQC（用于 New-View 选择 HighQC）
    update_node_prepare_qc(session, node_id, qc)
    
    # 如果收到 Commit 阶段的 QC，更新 lockedQC（HotStuff Safety 要求）
    if qc_phase == "commit":
        update_node_locked_qc(session, node_id, qc)
        print(f"节点 {node_id}: 收到 Commit QC（View {qc_view}），已更新 lockedQC")

async def handle_vote(session_id: str, vote_message: Dict[str, Any]):
    """
    Leader 汇总 VOTE，达到阈值生成 QC 并广播下一阶段（HotStuff 阶段推进）
    
    生成 QC 后，所有节点会收到 QC 并更新其 prepareQC/lockedQC 状态
    """
    session = get_session(session_id)
    if not session:
        return
    
    view = vote_message.get("view", session.get("current_view", 0))
    phase = vote_message.get("phase", "prepare")
    voter = vote_message.get("from")
    value = vote_message.get("value")
    
    leader_id = get_current_leader(session, view)
    if vote_message.get("to") != leader_id:
        print(f"投票目标不是当前Leader，忽略: {vote_message}")
        return
    
    # 检查投票的视图是否匹配
    if view != session["current_view"]:
        print(f"投票视图 {view} 不匹配当前视图 {session['current_view']}，忽略")
        return
    
    key = (view, phase, value)
    pending = session.setdefault("pending_votes", {})
    voters = pending.setdefault(key, set())
    voters.add(voter)
    
    threshold = get_quorum_threshold(session)
    if len(voters) < threshold:
        print(f"投票累积中: phase={phase}, view={view}, 收到 {len(voters)}/{threshold}")
        return
    
    # 达到阈值，生成 QC
    qc = {
        "phase": phase,
        "view": view,
        "signers": list(voters),
        "value": value,
    }
    
    next_phase = get_next_phase(phase)
    session["phase"] = next_phase
    session["phase_step"] += 1
    
    qc_message = {
        "from": leader_id,
        "to": "all",
        "type": "qc",
        "phase": phase,
        "next_phase": next_phase,
        "view": view,
        "qc": qc,
        "timestamp": datetime.now().isoformat()
    }
    
    # 将完整的 QC 广播消息写入会话历史
    session["messages"]["qc"].append(qc_message)
    
    # Leader 广播 QC 到所有节点（HotStuff 星型拓扑）
    n = session["config"]["nodeCount"]
    count_message_sent(session_id, is_broadcast=True, target_count=n - 1)
    await sio.emit('message_received', qc_message, room=session_id)
    await sio.emit('phase_update', {
        "phase": next_phase,
        "step": session["phase_step"],
        "leader": leader_id,
        "view": view
    }, room=session_id)
    
    print(f"Leader {leader_id} 收到 {len(voters)} 票，生成 {phase} QC 并进入 {next_phase} 阶段（View {view}）")
    
    # 通知所有节点处理 QC（更新 prepareQC/lockedQC）
    for node_id in range(n):
        await handle_qc_message(session_id, qc_message, node_id)
    
    pending[key] = voters

    # HotStuff 多阶段自动推进：在进入下一阶段后，调度机器人自动投票
    # next_phase 可能是 pre-commit / commit / decide
    if next_phase == "decide":
        # Decide 阶段完成，达成共识
        await finalize_consensus(session_id, "共识成功", f"View {view} 达成共识")
    else:
        try:
            asyncio.create_task(trigger_robot_votes(session_id, view, next_phase, value))
        except RuntimeError as e:
            print(f"调度 trigger_robot_votes 失败: {e}")
@sio.event
async def choose_normal_consensus(sid, data):
    """处理人类节点选择正常共识"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    
    session = get_session(session_id)
    if not session:
        return
    
    # 将此人类节点转为机器人代理模式
    print(f"人类节点 {node_id} 选择正常共识，切换为机器人代理模式")
    
    # 从人类节点列表中移除，加入机器人节点列表（本轮）
    if node_id in session["human_nodes"]:
        session["human_nodes"].remove(node_id)
    
    # 临时将此节点加入机器人节点列表
    if node_id not in session["robot_nodes"]:
        session["robot_nodes"].append(node_id)
        
        # 初始化机器人节点状态
        session["robot_node_states"][node_id] = {
            "received_pre_prepare": True,
            "received_prepare_count": len([m for m in session["messages"]["prepare"] if m["from"] != node_id]),
            "received_commit_count": len([m for m in session["messages"]["commit"] if m["from"] != node_id]),
            "sent_prepare": False,
            "sent_commit": False
        }
    
    # 根据当前阶段自动发送消息
    config = session["config"]
    
    if session["phase"] == "prepare" and node_id != 0:
        # 在准备阶段且不是主节点，发送准备消息
        # 标记为即将发送，防止robot_send_prepare_messages重复发送
        session["robot_node_states"][node_id]["sent_prepare"] = True
        asyncio.create_task(schedule_robot_prepare(session_id, node_id, config["proposalValue"]))
    elif session["phase"] == "commit":
        # 在提交阶段，发送提交消息
        # 标记为即将发送，防止robot_send_commit_messages重复发送
        session["robot_node_states"][node_id]["sent_commit"] = True
        asyncio.create_task(schedule_robot_commit(session_id, node_id, config["proposalValue"]))

async def schedule_robot_prepare(session_id: str, robot_id: int, value: int):
    """调度机器人节点在10秒后发送准备消息"""
    session = get_session(session_id)
    if not session:
        return
    
    current_round = session["current_round"]
    await asyncio.sleep(10)
    
    session = get_session(session_id)
    if not session:
        return
    
    # 检查轮次是否改变
    if session["current_round"] != current_round:
        print(f"轮次已改变（{current_round} -> {session['current_round']}），节点{robot_id}放弃发送准备消息")
        return
    
    await handle_robot_prepare(session_id, robot_id, value)

@sio.event
async def choose_byzantine_attack(sid, data):
    """处理人类节点选择拜占庭攻击"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    
    print(f"人类节点 {node_id} 选择拜占庭攻击模式")
    # 不需要特殊处理，人类节点保持在human_nodes列表中

@sio.event
async def ping(sid, data):
    """处理Ping消息"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    
    # 发送Pong响应
    pong_message = {
        "from": "server",
        "to": node_id,
        "type": "pong",
        "value": None,
        "phase": "ping",
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "customContent": f"服务器响应节点{node_id}的Ping"
    }
    
    await sio.emit('message_received', pong_message, room=session_id)
    print(f"节点 {node_id} 发送Ping，服务器响应Pong")

# 共识逻辑
async def check_and_start_consensus(session_id: str):
    """检查是否可以开始共识"""
    session = get_session(session_id)
    if not session:
        return
    
    config = session["config"]
    connected_count = len(connected_nodes.get(session_id, []))
    
    # 如果连接节点数达到要求，开始共识
    if connected_count >= config["nodeCount"]:
        await start_consensus(session_id)

async def start_consensus(session_id: str):
    """
    开始共识过程 - HotStuff 第一轮共识的初始化
    
    对于第一个 View（View 0），Leader 直接发送 Proposal（不需要 New-View）
    """
    session = get_session(session_id)
    if not session:
        return
    
    session["status"] = "running"
    session["phase"] = "new-view"  # HotStuff 第一阶段是 new-view
    session["phase_step"] = 0
    
    print(f"会话 {session_id} 开始 HotStuff 共识流程 (View 0)")
    
    # 通知所有节点进入 new-view 阶段
    await sio.emit('phase_update', {
        "phase": "new-view",
        "step": 0,
        "leader": session["leader_id"],
        "view": session["current_view"]
    }, room=session_id)
    
    # 第一个 View 的 Leader 直接发送 Proposal（不需要收集 NEW-VIEW）
    await robot_send_pre_prepare(session_id, highQC=None)

async def start_prepare_phase(session_id: str):
    """开始准备阶段"""
    session = get_session(session_id)
    if not session:
        return
    
    session["phase"] = "prepare"
    session["phase_step"] = 1
    
    config = session["config"]
    
    # 通知所有节点进入准备阶段
    await sio.emit('phase_update', {
        "phase": "prepare",
        "step": 1,
        "isMyTurn": True
    }, room=session_id)
    
    print(f"会话 {session_id} 进入准备阶段")

async def check_prepare_phase(session_id: str):
    """检查准备阶段是否完成"""
    session = get_session(session_id)
    if not session:
        return
    
    config = session["config"]
    prepare_messages = session["messages"]["prepare"]
    
    # 计算故障节点数 f = floor((n-1)/3)
    n = config["nodeCount"]
    f = (n - 1) // 3
    required_correct_messages = 2 * f + 1  # 需要2f+1个正确消息
    
    # 统计发送正确信息的不同节点（value=0）
    correct_nodes = set()
    for msg in prepare_messages:
        if msg.get("value") == config["proposalValue"]:  # 正确信息
            correct_nodes.add(msg["from"])
    
    print(f"准备阶段检查 - 总节点数: {n}, 故障节点数: {f}")
    print(f"准备阶段检查 - 需要正确消息数: {required_correct_messages}, 实际正确消息节点数: {len(correct_nodes)}")
    print(f"准备阶段检查 - 发送正确消息的节点: {correct_nodes}")
    
    # 检查是否收到足够多的正确消息
    if len(correct_nodes) >= required_correct_messages:
        print(f"准备阶段完成（收到{len(correct_nodes)}个正确消息），进入提交阶段")
        await start_commit_phase(session_id)
    else:
        print(f"准备阶段未完成，还需要 {required_correct_messages - len(correct_nodes)} 个正确消息")

async def start_commit_phase(session_id: str):
    """开始提交阶段"""
    session = get_session(session_id)
    if not session:
        return
    
    session["phase"] = "commit"
    session["phase_step"] = 2
    
    # 通知所有节点进入提交阶段
    await sio.emit('phase_update', {
        "phase": "commit",
        "step": 2,
        "isMyTurn": True
    }, room=session_id)
    
    print(f"会话 {session_id} 进入提交阶段")
    
    # 通知所有机器人节点检查是否可以发送提交消息
    await check_robot_nodes_ready_for_commit(session_id)

async def check_commit_phase(session_id: str):
    """检查提交阶段是否完成"""
    session = get_session(session_id)
    if not session:
        return
    
    config = session["config"]
    commit_messages = session["messages"]["commit"]
    
    # 计算故障节点数 f = floor((n-1)/3)
    n = config["nodeCount"]
    f = (n - 1) // 3
    
    # 统计发送正确信息和错误信息的不同节点
    correct_nodes = set()
    error_nodes = set()
    
    for msg in commit_messages:
        if msg.get("value") == config["proposalValue"]:  # 正确信息
            correct_nodes.add(msg["from"])
        else:  # 错误信息
            error_nodes.add(msg["from"])
    
    print(f"提交阶段检查 - 总节点数: {n}, 故障节点数: {f}")
    print(f"提交阶段检查 - 发送正确消息的节点数: {len(correct_nodes)}")
    print(f"提交阶段检查 - 发送错误消息的节点数: {len(error_nodes)}")
    print(f"提交阶段检查 - 正确消息节点: {correct_nodes}")
    print(f"提交阶段检查 - 错误消息节点: {error_nodes}")
    print(f"提交阶段检查 - 需要正确消息数: {2*f+1}, 需要错误消息数: {f+1}")
    
    # 判断共识结果（基于正确/错误消息数量）
    if len(correct_nodes) >= 2 * f + 1:  # 包括自己，需要2f+1个正确消息
        print(f"共识成功 - 收到{len(correct_nodes)}个正确消息（需要{2*f+1}个）")
        print(f"发送共识结果: 共识成功")
        await finalize_consensus(session_id, "共识成功", f"收到{len(correct_nodes)}个正确消息")
    elif len(error_nodes) >= f + 1:  # 包括自己，需要f+1个错误消息
        print(f"共识失败 - 收到{len(error_nodes)}个错误消息（需要{f+1}个）")
        print(f"发送共识结果: 共识失败")
        await finalize_consensus(session_id, "共识失败", f"收到{len(error_nodes)}个错误消息")
    else:
        print(f"提交阶段等待中 - 正确消息:{len(correct_nodes)}, 错误消息:{len(error_nodes)}")

async def finalize_consensus(session_id: str, status: str = "共识完成", description: str = "共识已完成"):
    """
    完成共识（HotStuff Decide 阶段达成共识）
    
    注意：HotStuff 中，一旦进入 Decide 阶段即达成共识，不会再有下一"轮"
    如果需要继续共识新的提案，应该开始新的 View（通过 New-View 机制）
    """
    session = get_session(session_id)
    if not session:
        return
    
    # 防止重复调用（基于 view）
    current_view = session["current_view"]
    if session.get("consensus_finalized_view") == current_view:
        print(f"View {current_view} 共识已完成，跳过重复调用")
        return
    
    session["consensus_finalized_view"] = current_view
    print(f"View {current_view} 共识完成处理开始")
    
    # 取消超时任务
    if session.get("timeout_task"):
        session["timeout_task"].cancel()
        print(f"View {current_view} 共识已完成，取消超时任务")
    
    session["phase"] = "completed"
    session["phase_step"] = 3
    session["status"] = "completed"
    
    config = session["config"]
    
    # 创建共识结果
    consensus_result = {
        "status": status,
        "description": description,
        "stats": {
            "expected_nodes": config["nodeCount"],
            "expected_prepare_nodes": config["nodeCount"] - 1,
            "total_messages": len(session["messages"]["prepare"]) + len(session["messages"]["commit"])
        }
    }
    
    session["consensus_result"] = consensus_result
    
    # ================= 通信复杂度统计报告（HotStuff vs PBFT） =================
    network_stats = session.get("network_stats", {})
    actual_messages = network_stats.get("total_messages_sent", 0)
    n = config["nodeCount"]
    pbft_theoretical = 2 * n * n     # 2 * N^2
    hotstuff_theoretical = 4 * n     # 4 * N
    optimization_ratio = pbft_theoretical / actual_messages if actual_messages > 0 else 0.0
    
    print("\n" + "=" * 60)
    print("📊 HotStuff 通信复杂度分析报告")
    print("=" * 60)
    print(f"[算法] 当前算法类型: HotStuff")
    print(f"[配置] 节点总数 N = {n}")
    print(f"[实测] 实际产生消息数: {actual_messages}")
    print(f"[对比] PBFT 理论预期消息数: {pbft_theoretical} (≈ 2 × N^2)")
    print(f"[对比] HotStuff 理论预期消息数: {hotstuff_theoretical} (≈ 4 × N)")
    print("-" * 60)
    if actual_messages > 0:
        print(f"🚀 结论: 通信复杂度相对于 PBFT 理论值降低约 {optimization_ratio:.2f} 倍")
    else:
        print("⚠️  警告: 未统计到任何共识消息，无法计算优化倍数")
    print("=" * 60 + "\n")
    
    # 广播共识结果
    print(f"准备发送共识结果: {consensus_result}")
    await sio.emit('consensus_result', consensus_result, room=session_id)
    print(f"已发送共识结果到房间: {session_id}")
    
    # 更新阶段
    await sio.emit('phase_update', {
        "phase": "completed",
        "step": 3,
        "isMyTurn": False
    }, room=session_id)
    
    print(f"会话 {session_id} View {session['current_view']} 共识完成: {status}")
    
    # 保存共识历史（使用 view 作为标识）
    session["consensus_history"].append({
        "view": session["current_view"],
        "status": status,
        "description": description,
        "timestamp": datetime.now().isoformat()
    })
    
    # HotStuff 中，一次共识完成不代表需要"下一轮"
    # 如果需要继续共识，应该通过 New-View 机制开始新的 View
    # 这里我们保持会话状态为 completed，不再自动启动下一轮
    print(f"View {session['current_view']} 共识完成，会话状态设为 completed")

async def handle_consensus_timeout(session_id: str, view: int):
    """
    处理共识超时（HotStuff View Change 机制）
    
    超时不代表失败，而是触发 View Change：
    1. 所有节点发送 NEW-VIEW 消息给 Next Leader
    2. Next Leader 收集 2f+1 个 NEW-VIEW 消息后选出 HighQC
    3. 进入下一个视图继续共识
    
    参数:
        session_id: 会话ID
        view: 超时的视图号
    """
    await asyncio.sleep(40)  # 等待40秒
    
    session = get_session(session_id)
    if not session:
        return
    
    # 检查是否仍然在同一视图且未完成共识
    if session["current_view"] == view and session["status"] == "running":
        print(f"View {view} 共识超时（40秒未完成），触发 View Change")
        
        # 清除超时任务引用
        session["timeout_task"] = None
        
        # 触发 View Change（HotStuff Liveness 机制）
        await trigger_view_change(session_id, view)

async def trigger_view_change(session_id: str, old_view: int):
    """
    触发 View Change（HotStuff New-View 机制）
    
    所有节点发送 NEW-VIEW 消息给 Next Leader，携带自己最高的 prepareQC
    Next Leader 收集 2f+1 个 NEW-VIEW 消息后，选择最高的 HighQC 并发送 Proposal
    """
    session = get_session(session_id)
    if not session:
        return
    
    new_view = old_view + 1
    n = session["config"]["nodeCount"]
    next_leader_id = get_current_leader(session, new_view)
    
    print(f"触发 View Change: View {old_view} -> View {new_view} (Next Leader: {next_leader_id})")
    
    # 更新当前视图
    session["current_view"] = new_view
    session["leader_id"] = next_leader_id
    
    # 所有节点发送 NEW-VIEW 消息给 Next Leader
    for node_id in range(n):
        node_state = session["node_states"].get(node_id, {})
        highQC = node_state.get("highQC")  # 节点最高的 prepareQC
        
        new_view_msg = {
            "from": node_id,
            "to": next_leader_id,
            "type": "new_view",
            "view": new_view,
            "old_view": old_view,
            "highQC": highQC,  # 携带最高的 QC
            "timestamp": datetime.now().isoformat()
        }
        
        session["messages"]["new_view"].append(new_view_msg)
        
        # 如果是机器人节点，直接在后端处理；如果是人类节点，通过 WebSocket 发送
        if node_id in session.get("robot_nodes", []):
            # 机器人节点：直接在后端记录
            print(f"节点 {node_id}: 发送 NEW-VIEW 消息给 Next Leader {next_leader_id} (highQC.view={highQC.get('view') if highQC else None})")
        else:
            # 人类节点：通过 WebSocket 发送
            node_sid = node_sockets.get(session_id, {}).get(node_id)
            if node_sid:
                count_message_sent(session_id, is_broadcast=False)
                await sio.emit('message_received', new_view_msg, room=node_sid)
        
        # Leader 收集 NEW-VIEW 消息
        if node_id == next_leader_id:
            continue  # Leader 不给自己发送
        
        pending_new_views = session.setdefault("pending_new_views", {})
        if new_view not in pending_new_views:
            pending_new_views[new_view] = {}
        pending_new_views[new_view][node_id] = new_view_msg
    
    # 统计消息数（星型拓扑：N-1 个节点发送给 Leader）
    count_message_sent(session_id, is_broadcast=False, target_count=n - 1)
    
    # 通知所有节点进入 New-View 阶段
    await sio.emit('phase_update', {
        "phase": "new-view",
        "step": 0,
        "leader": next_leader_id,
        "view": new_view
    }, room=session_id)
    
    # Next Leader 检查是否已收集到足够的 NEW-VIEW 消息并开始新视图共识
    await start_new_view_consensus(session_id, new_view)

async def start_next_round(session_id: str):
    """启动下一轮共识"""
    await asyncio.sleep(10)
    
    session = get_session(session_id)
    if not session:
        return
    
    # 增加轮次和视图（HotStuff视图轮换）
    session["current_round"] += 1
    session["current_view"] += 1
    current_round = session["current_round"]
    # 根据当前视图更新 Leader
    session["leader_id"] = get_current_leader(session)
    
    # 重置会话状态
    session["status"] = "running"
    session["phase"] = "pre-prepare"
    session["phase_step"] = 0
    session["consensus_result"] = None
    # 重置网络统计（每轮重新开始统计）
    session["network_stats"] = {
        "total_messages_sent": 0,
        "phases_count": 0
    }
    
    # 不再清空消息，保留历史轮次的消息
    # 所有消息通过 round 字段区分不同轮次
    # session["messages"] 保持累积，不清空
    
    # 将临时机器人节点移回人类节点列表
    config = session["config"]
    original_robot_count = config["robotNodes"]
    
    print(f"第{current_round}轮开始 - 原始机器人节点数: {original_robot_count}")
    print(f"第{current_round}轮开始 - 当前机器人节点: {session['robot_nodes']}")
    print(f"第{current_round}轮开始 - 当前人类节点: {session['human_nodes']}")
    
    # 找出临时加入的机器人节点（ID >= original_robot_count）
    temp_robot_nodes = [node_id for node_id in session["robot_nodes"] if node_id >= original_robot_count]
    
    print(f"第{current_round}轮开始 - 临时机器人节点: {temp_robot_nodes}")
    
    # 将临时机器人节点移回人类节点列表
    for node_id in temp_robot_nodes:
        if node_id in session["robot_nodes"]:
            session["robot_nodes"].remove(node_id)
        if node_id not in session["human_nodes"]:
            session["human_nodes"].append(node_id)
        # 清除临时机器人节点状态
        if node_id in session["robot_node_states"]:
            del session["robot_node_states"][node_id]
    
    print(f"已将临时机器人节点 {temp_robot_nodes} 移回人类节点列表")
    print(f"第{current_round}轮开始后 - 机器人节点: {session['robot_nodes']}")
    print(f"第{current_round}轮开始后 - 人类节点: {session['human_nodes']}")
    
    # 重置机器人节点状态（只重置原始机器人节点）
    for robot_id in session["robot_nodes"]:
        session["robot_node_states"][robot_id] = {
            "received_pre_prepare": False,
            "received_prepare_count": 0,
            "received_commit_count": 0,
            "sent_prepare": False,
            "sent_commit": False
        }
    
    print(f"会话 {session_id} 开始第{current_round}轮共识")
    
    # 通知所有节点（包括等待中的人类节点）进入新一轮共识
    await sio.emit('new_round', {
        "round": current_round,
        "view": session["current_view"],
        "leader": session["leader_id"],
        "phase": "pre-prepare",
        "step": 0
    }, room=session_id)
    
    # 通知所有节点进入预准备阶段
    await sio.emit('phase_update', {
        "phase": "pre-prepare",
        "step": 0,
        "isMyTurn": False
    }, room=session_id)
    
    print(f"第{current_round}轮开始，所有节点（包括新加入的人类节点）现在可以参与共识")
    
    # 机器人提议者发送预准备消息（注意：HotStuff 中应该通过 View Change 继续，而不是"下一轮"）
    # 这里保留以兼容旧代码，但实际上应该通过 trigger_view_change 来继续共识
    await robot_send_pre_prepare(session_id, highQC=None)

# ==================== 辅助函数 ====================

async def broadcast_to_online_nodes(session_id: str, event: str, data: Any):
    """只向在线的人类节点广播消息，机器人节点总是在线"""
    session = get_session(session_id)
    if not session:
        return
    
    # 向所有在线的人类节点发送
    if session_id in node_sockets:
        for node_id, sid in node_sockets[session_id].items():
            if node_id in session["human_nodes"]:  # 只向人类节点发送
                await sio.emit(event, data, room=sid)
    
    # 机器人节点不需要接收WebSocket消息，因为它们在后端自动处理

# ==================== 机器人节点管理 ====================

async def create_robot_nodes_and_start(session_id: str, robot_count: int):
    """创建机器人节点并立即启动PBFT流程"""
    await asyncio.sleep(1)  # 等待会话初始化
    
    session = get_session(session_id)
    if not session:
        return
    
    print(f"创建{robot_count}个机器人节点")
    
    # 机器人节点是0到robotNodes-1，人类节点从robotNodes开始编号
    for robot_id in range(robot_count):
        session["robot_nodes"].append(robot_id)
        connected_nodes[session_id].append(robot_id)
        print(f"机器人节点 {robot_id} 已创建")
        
        # 初始化机器人节点状态
        session["robot_node_states"][robot_id] = {
            "received_pre_prepare": False,
            "received_prepare_count": 0,
            "received_commit_count": 0,
            "sent_prepare": False,
            "sent_commit": False
        }
    
    # 立即开始PBFT共识流程（不等待人类节点）
    print(f"机器人节点准备完毕，立即开始PBFT共识流程")
    await start_pbft_process(session_id)

async def start_pbft_process(session_id: str):
    """
    启动 HotStuff 共识流程（函数名保留为 start_pbft_process 以兼容旧代码）
    
    对于第一个 View（View 0），Leader 直接发送 Proposal（不需要 New-View）
    """
    session = get_session(session_id)
    if not session:
        return
    
    # 更新会话状态
    session["status"] = "running"
    session["phase"] = "new-view"  # HotStuff 第一阶段是 new-view
    session["phase_step"] = 0
    
    # 通知所有节点进入 new-view 阶段
    await sio.emit('phase_update', {
        "phase": "new-view",
        "step": 0,
        "leader": session["leader_id"],
        "view": session["current_view"]
    }, room=session_id)
    
    print(f"会话 {session_id} 开始 HotStuff 共识流程 (View {session['current_view']})")
    
    # 第一个 View 的 Leader 直接发送 Proposal（不需要收集 NEW-VIEW）
    await robot_send_pre_prepare(session_id, highQC=None)

async def start_new_view_consensus(session_id: str, view: int):
    """
    开始新视图的共识（HotStuff New-View 机制）
    
    如果 Leader 已收集到 2f+1 个 NEW-VIEW 消息，则选择最高的 HighQC 并发送 Proposal
    """
    session = get_session(session_id)
    if not session:
        return
    
    leader_id = get_current_leader(session, view)
    pending_new_views = session.get("pending_new_views", {}).get(view, {})
    
    n = session["config"]["nodeCount"]
    f = (n - 1) // 3
    threshold = 2 * f + 1
    
    if len(pending_new_views) < threshold:
        print(f"View {view}: Leader {leader_id} 仅收集到 {len(pending_new_views)}/{threshold} 个 NEW-VIEW 消息，等待更多")
        return
    
    # 选择最高的 HighQC（New-View 机制的核心）
    highQC = None
    max_view = -1
    for node_id, new_view_msg in pending_new_views.items():
        qc = new_view_msg.get("highQC")
        if qc:
            qc_view = qc.get("view", -1)
            if qc_view > max_view:
                max_view = qc_view
                highQC = qc
    
    print(f"View {view}: Leader {leader_id} 选出 HighQC (view={max_view})，开始发送 Proposal")
    
    # 如果 Leader 是机器人节点，自动发送 Proposal
    if leader_id in session.get("robot_nodes", []):
        await robot_send_pre_prepare(session_id, highQC)
    else:
        print(f"View {view}: Leader {leader_id} 是人类节点，等待手动发送 Proposal")

async def robot_send_pre_prepare(session_id: str, highQC: Optional[Dict] = None):
    """
    Leader 发送 Proposal 消息（HotStuff PRE-PREPARE）
    
    参数:
        session_id: 会话ID
        highQC: 从 New-View 消息中选出的最高 QC（可选）
    """
    session = get_session(session_id)
    if not session:
        return
    
    # 防止重复调用（基于 view）
    current_view = session["current_view"]
    if session.get("last_pre_prepare_view") == current_view:
        print(f"View {current_view} 的 Proposal 已发送，跳过重复调用")
        return
    
    session["last_pre_prepare_view"] = current_view
    
    config = session["config"]
    proposer_id = get_current_leader(session)  # 当前视图的Leader作为提议者
    
    # 只有当 Leader 是机器人节点时才自动发送
    if proposer_id not in session.get("robot_nodes", []):
        print(f"Leader {proposer_id} 是人类节点，等待人类操作")
        return
    
    # 如果提供了 highQC，使用 highQC 的 value；否则使用配置的 proposalValue
    proposal_value = config["proposalValue"]
    if highQC:
        proposal_value = highQC.get("value", config["proposalValue"])
    
    # 发送 Proposal 消息（Leader广播Proposal，HotStuff 星型拓扑）
    message = {
        "from": proposer_id,
        "to": "all",
        "type": "pre_prepare",
        "value": proposal_value,
        "phase": "prepare",  # HotStuff 中 Proposal 开启 Prepare 阶段
        "view": current_view,
        "qc": highQC,  # 携带 HighQC（如果有）
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "isRobot": True
    }
    
    session["messages"]["pre_prepare"].append(message)
    
    # 广播消息：Leader -> All（HotStuff 星型拓扑）
    count_message_sent(session_id, is_broadcast=True, target_count=config["nodeCount"] - 1)
    await sio.emit('message_received', message, room=session_id)
    
    print(f"Leader {proposer_id} (View {current_view}) 发送了 Proposal 消息: value={proposal_value}, highQC.view={highQC.get('view') if highQC else None}")
    
    # 进入准备阶段
    await asyncio.sleep(1)
    session["phase"] = "prepare"
    session["phase_step"] = 1
    
    await sio.emit('phase_update', {
        "phase": "prepare",
        "step": 1,
        "leader": proposer_id,
        "view": current_view
    }, room=session_id)
    
    print(f"会话 {session_id} View {current_view} 进入准备阶段")
    
    # 启动超时任务（超时后触发 View Change，而不是结束）
    timeout_task = asyncio.create_task(handle_consensus_timeout(session_id, current_view))
    session["timeout_task"] = timeout_task
    print(f"View {current_view} 共识超时检查已启动（40秒后触发 View Change）")
    
    # 标记所有机器人节点已收到 Proposal（它们会自动进行 SafeNode 检查并投票）
    for robot_id in session.get("robot_nodes", []):
        if robot_id != proposer_id:  # Leader 不给自己投票
            session["robot_node_states"][robot_id]["received_pre_prepare"] = True
    
    # 机器人节点自动发送 Prepare 投票（10秒后，会进行 SafeNode 检查）
    asyncio.create_task(robot_send_prepare_messages(session_id))

async def robot_send_prepare_messages(session_id: str):
    """
    机器人节点自动发送 Prepare 阶段的 VOTE（单播给 Leader）
    
    在发送前会进行 SafeNode 检查，只有通过检查的节点才会投票
    """
    session = get_session(session_id)
    if not session:
        return
    
    config = session["config"]
    current_view = session["current_view"]
    
    # 找到最新的 Proposal 消息
    proposal_msgs = [m for m in session["messages"]["pre_prepare"] if m.get("view") == current_view]
    if not proposal_msgs:
        print(f"View {current_view}: 未找到 Proposal 消息，机器人节点不投票")
        return
    
    proposal_msg = proposal_msgs[-1]  # 取最新的
    proposal_value = proposal_msg.get("value")
    proposal_qc = proposal_msg.get("qc")
    
    # 等待10秒后发送准备阶段投票
    print(f"View {current_view}: 机器人节点将在10秒后发送 VOTE(prepare) 给 Leader")
    await asyncio.sleep(10)
    
    session = get_session(session_id)
    if not session:
        return
    
    # 检查视图是否改变
    if session["current_view"] != current_view:
        print(f"视图已改变（{current_view} -> {session['current_view']}），放弃发送投票")
        return
    
    # 所有机器人验证者（除了Leader）进行 SafeNode 检查并发送投票
    leader_id = get_current_leader(session)
    for robot_id in session.get("robot_nodes", []):
        if robot_id == leader_id:  # Leader不给自己投票
            continue
        
        if session["robot_node_states"][robot_id].get("sent_prepare"):
            continue  # 已经发送过了
        
        # SafeNode 检查（HotStuff Safety 要求）
        if not check_safe_node(session, robot_id, current_view, proposal_value, proposal_qc):
            print(f"机器人节点 {robot_id}: SafeNode 检查失败，拒绝投票（View {current_view}）")
            continue
        
        # 通过 SafeNode 检查，发送投票
        await handle_robot_prepare(session_id, robot_id, proposal_value)
        session["robot_node_states"][robot_id]["sent_prepare"] = True

async def handle_robot_prepare(session_id: str, robot_id: int, value: int):
    """
    处理机器人节点的 Prepare 阶段投票（VOTE -> Leader 单播，HotStuff 星型拓扑）
    
    注意：此函数假设已经通过了 SafeNode 检查
    """
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    leader_id = get_current_leader(session, current_view)
    leader_sid = node_sockets.get(session_id, {}).get(leader_id)
    
    vote_message = {
        "from": robot_id,
        "to": leader_id,
        "type": "vote",
        "value": value,
        "phase": "prepare",
        "view": current_view,
        "qc": None,
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "isRobot": True
    }
    
    session["messages"]["vote"].append(vote_message)
    
    if leader_sid:
        count_message_sent(session_id, is_broadcast=False)
        await sio.emit('message_received', vote_message, room=leader_sid)
        print(f"机器人节点 {robot_id} 向 Leader {leader_id} 发送 VOTE(prepare) [View {current_view}]")
    else:
        print(f"Leader {leader_id} 不在线，缓存机器人投票")
    
    await handle_vote(session_id, vote_message)

async def check_robot_nodes_ready_for_commit(session_id: str):
    """HotStuff 中提交阶段由 Leader 收齐QC 后推进，这里仅保留占位"""
    # 在 HotStuff 模式下，机器人投票由 Leader 汇总生成 QC 触发下一阶段
    return

async def schedule_robot_commit(session_id: str, robot_id: int, value: int):
    """调度机器人节点在10秒后发送提交消息"""
    session = get_session(session_id)
    if not session:
        return
    
    current_round = session["current_round"]
    await asyncio.sleep(10)
    
    session = get_session(session_id)
    if not session:
        return
    
    # 检查轮次是否改变
    if session["current_round"] != current_round:
        print(f"轮次已改变（{current_round} -> {session['current_round']}），节点{robot_id}放弃发送提交消息")
        return
    
    await handle_robot_commit(session_id, robot_id, value)

async def handle_robot_commit(session_id: str, robot_id: int, value: int):
    """处理机器人节点的提交阶段投票（VOTE -> Leader 单播）"""
    session = get_session(session_id)
    if not session:
        return
    
    leader_id = get_current_leader(session)
    leader_sid = node_sockets.get(session_id, {}).get(leader_id)
    
    vote_message = {
        "from": robot_id,
        "to": leader_id,
        "type": "vote",
        "value": value,
        "phase": "commit",
        "view": session["current_view"],
        "round": session["current_round"],  # 兼容旧逻辑
        "qc": None,
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "isRobot": True
    }
    
    session["messages"]["vote"].append(vote_message)
    
    if leader_sid:
        count_message_sent(session_id, is_broadcast=False)
        await sio.emit('message_received', vote_message, room=leader_sid)
        print(f"机器人节点 {robot_id} 向 Leader {leader_id} 发送 VOTE(commit)")
    else:
        print(f"Leader {leader_id} 不在线，缓存机器人投票")
    
    await handle_vote(session_id, vote_message)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="127.0.0.1", port=8000) 