"""
FastAPI 应用入口点

此文件作为应用的入口点，负责：
- 初始化 FastAPI 应用
- 配置 CORS
- 创建 Socket.IO 服务器和应用
- 定义 HTTP 路由
- 启动服务器
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import socketio

# 导入全局状态和 Socket.IO 服务器
from state import sio, sessions, connected_nodes, node_sockets, get_session

# 导入数据模型
from models import SessionConfig

# 导入业务逻辑函数
from socket_handlers import create_session
from topology_manager import get_topology_info, is_connection_allowed

# 持久化模块
import database

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

# 创建ASGI应用（sio 从 state 模块导入）
socket_app = socketio.ASGIApp(sio, app)

# 导入 Socket.IO 事件处理（确保事件处理器被注册）
import socket_handlers  # 这会注册所有 @sio.event 装饰器


# ==================== 启动时加载持久化会话 ====================

@app.on_event("startup")
async def on_startup():
    """应用启动时初始化 SQLite，并恢复会话状态"""
    database.init_db()

    # 从数据库加载所有会话状态
    persisted_sessions = database.load_all_sessions()
    print(f"[startup] 从 SQLite 加载 {len(persisted_sessions)} 个会话")

    for session_id, state in persisted_sessions.items():
        # 防御性处理：确保是 dict
        if not isinstance(state, dict):
            continue

        # 如果之前是 running 状态，重启后无法恢复后台任务，统一恢复为 waiting
        if state.get("status") == "running":
            state["status"] = "waiting"
            state["phase"] = "waiting"
            state["phase_step"] = 0

        # 恢复历史记录（从 history 表加载最新快照）
        history_items = database.load_history(session_id)
        state["consensus_history"] = history_items

        # 恢复到内存中的全局 sessions
        sessions[session_id] = state

        # 已连接节点列表可以从状态中恢复（如果没有则置空）
        connected_nodes[session_id] = state.get("connected_nodes", [])
        # WebSocket 连接无法持久化，重启后需要重新连接
        node_sockets[session_id] = {}

    print("[startup] 会话状态已从 SQLite 恢复到内存")


# ==================== HTTP 路由 ====================

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
        raise HTTPException(status_code=404, detail="Session not found")
    
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
        raise HTTPException(status_code=404, detail="Session not found")
    
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
    
    return {"message": "Session deleted"}

@app.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """获取会话状态"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
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
        raise HTTPException(status_code=404, detail="Session not found")
    
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
        raise HTTPException(status_code=409, detail="All nodes occupied")
    
    return {
        "nodeId": available_node,
        "sessionId": session_id,
        "role": "Proposer" if available_node == 0 else "Validator",
        "totalNodes": total_nodes,
        "connectedNodes": len(connected)
    }

@app.get("/api/sessions/{session_id}/connected-nodes")
async def get_connected_nodes(session_id: str):
    """获取已连接的节点列表"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    connected = connected_nodes.get(session_id, [])
    return {
        "sessionId": session_id,
        "connectedNodes": connected,
        "totalNodes": session["config"]["nodeCount"]
    }

@app.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str, round: Optional[int] = None):
    """获取会话的真实消息历史，适配 HotStuff 表格和动画（支持双层分层动画）"""
    from typing import List, Dict, Any
    
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    config = session["config"]
    messages = session["messages"]
    n = config["nodeCount"]
    topology = config["topology"]
    branch_count = config.get("branchCount", 2)
    is_double_layer = branch_count > 1 and n >= branch_count * 2
    
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

    # === 关键修复：从历史消息中提取该轮次的真实 View ===
    target_view = round  # 默认 fallback（假设 round 等于 view）
    
    # 尝试从该轮次的消息中获取真实 view
    all_round_msgs = []
    if messages.get("pre_prepare"):
        all_round_msgs.extend([m for m in messages["pre_prepare"] if m.get("round") == round])
    if messages.get("vote"):
        all_round_msgs.extend([m for m in messages["vote"] if m.get("round") == round])
    if messages.get("qc"):
        all_round_msgs.extend([m for m in messages["qc"] if m.get("round") == round])
    
    # 1. 确定该轮次的最终视图 (Target View)
    if all_round_msgs:
        # 找出该轮次涉及的所有 view，取最大值（通常是最终达成共识的 view）
        views = set(m.get("view") for m in all_round_msgs if "view" in m)
        if views:
            target_view = max(views)
    
    # 计算历史时刻的 Global Leader（使用历史视图）
    historical_leader_id = target_view % n
    print(f"[get_session_history] Round {round}: 过滤显示最终 View {target_view}, Leader ID = {historical_leader_id}")

    # 2. 准备数据容器
    table_messages: List[Dict[str, Any]] = []      # 表格用（合并广播，含phase）
    animation_sequence: List[List[Dict[str, Any]]] = []  # 动画用（拆分广播，按步骤）
    
    # 辅助函数：按轮次过滤
    def get_msgs(key, r):
        return [m for m in messages.get(key, []) if m.get("round") == r]
    
    # 辅助函数：按视图过滤消息（只保留属于 target_view 的消息）
    # 这样可以避免 View 0 (超时) 和 View 1 (成功) 的消息混在一起导致动画错乱
    def filter_msgs_by_view(msgs, view):
        return [m for m in msgs if m.get("view") == view]
    
    # 辅助函数：获取节点的拓扑信息（强制使用历史视图）
    def get_node_topology(node_id):
        return get_topology_info(session, node_id, view=target_view)

    # 使用过滤后的消息列表：只保留属于 target_view 的消息
    round_pre_prepare = filter_msgs_by_view(get_msgs("pre_prepare", round), target_view)
    round_votes = filter_msgs_by_view(get_msgs("vote", round), target_view)
    round_qc = filter_msgs_by_view(get_msgs("qc", round), target_view)

    # === 构建 HotStuff 7步 流程（支持双层分层动画）===

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
        
        if is_double_layer:
            # 双层模式：Root -> Group Leaders -> Members（分两步）
            # 子帧 1: Root -> Group Leaders
            step1a: List[Dict[str, Any]] = []
            # 子帧 2: Group Leaders -> Members
            step1b: List[Dict[str, Any]] = []
            
            for dst in range(n):
                if dst == src:
                    continue
                dst_info = get_node_topology(dst)
                if dst_info["role"] == "group_leader":
                    step1a.append({"src": src, "dst": dst, "value": value, "type": "proposal", "dst_type": "group_leaders"})
                elif dst_info["role"] == "member":
                    # 找到该 Member 的 Group Leader
                    gl_id = dst_info["parent_id"]
                    step1b.append({"src": gl_id, "dst": dst, "value": value, "type": "proposal", "dst_type": "group_members"})
            
            if step1a:
                animation_sequence.append(step1a)
            if step1b:
                animation_sequence.append(step1b)
        else:
            # 单层模式：直接广播
            if msg.get("to") == "all":
                for dst in range(n):
                    if dst != src and is_connection_allowed(src, dst, n, topology, branch_count):
                        step1_anim.append({"src": src, "dst": dst, "value": value, "type": "proposal"})
            else:
                step1_anim.append({"src": src, "dst": msg.get("to"), "value": value, "type": "proposal"})
            if step1_anim:
                animation_sequence.append(step1_anim)

    # Step 2: Prepare Vote (All -> Leader) [Phase: Prepare]
    step2_votes: List[Dict[str, Any]] = []
    for msg in round_votes:
        if msg.get("phase") == "prepare":
            m = {"src": msg["from"], "dst": msg["to"], "value": msg.get("value"), "type": "vote", "phase": "prepare"}
            step2_votes.append(m)
            table_messages.append(m)
    
    if is_double_layer:
        # 双层模式：Member -> Group Leader -> Root（分两步）
        # 子帧 1: Member -> Group Leader
        step2a: List[Dict[str, Any]] = []
        # 子帧 2: Group Leader -> Root
        step2b: List[Dict[str, Any]] = []
        
        for vote in step2_votes:
            src_id = vote["src"]
            src_info = get_node_topology(src_id)
            dst_id = vote["dst"]
            
            if src_info["role"] == "member":
                # Member 投票给 Group Leader
                gl_id = src_info["parent_id"]
                step2a.append({"src": src_id, "dst": gl_id, "value": vote["value"], "type": "vote", "phase": "prepare"})
            elif src_info["role"] == "group_leader" and dst_id == historical_leader_id:
                # Group Leader 投票给 Root（使用历史 Leader ID）
                step2b.append({"src": src_id, "dst": dst_id, "value": vote["value"], "type": "vote", "phase": "prepare"})
        
        if step2a:
            animation_sequence.append(step2a)
        if step2b:
            animation_sequence.append(step2b)
    else:
        if step2_votes:
            animation_sequence.append(step2_votes)

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
            
            if is_double_layer:
                # 双层模式：Root -> Group Leaders -> Members（分两步）
                step3a: List[Dict[str, Any]] = []
                step3b: List[Dict[str, Any]] = []
                
                for dst in range(n):
                    if dst == src:
                        continue
                    dst_info = get_node_topology(dst)
                    if dst_info["role"] == "group_leader":
                        step3a.append({"src": src, "dst": dst, "value": value, "type": "qc", "dst_type": "group_leaders"})
                    elif dst_info["role"] == "member":
                        gl_id = dst_info["parent_id"]
                        step3b.append({"src": gl_id, "dst": dst, "value": value, "type": "qc", "dst_type": "group_members"})
                
                if step3a:
                    animation_sequence.append(step3a)
                if step3b:
                    animation_sequence.append(step3b)
            else:
                if msg.get("to") == "all":
                    for dst in range(n):
                        if dst != src and is_connection_allowed(src, dst, n, topology, branch_count):
                            step3_anim.append({"src": src, "dst": dst, "value": value, "type": "qc"})
                if step3_anim:
                    animation_sequence.append(step3_anim)

    # Step 4: Pre-Commit Vote (All -> Leader) [Phase: Pre-Commit]
    step4_votes: List[Dict[str, Any]] = []
    for msg in round_votes:
        if msg.get("phase") == "pre-commit": 
            m = {"src": msg["from"], "dst": msg["to"], "value": msg.get("value"), "type": "vote", "phase": "pre-commit"}
            step4_votes.append(m)
            table_messages.append(m)
    
    if is_double_layer:
        step4a: List[Dict[str, Any]] = []
        step4b: List[Dict[str, Any]] = []
        
        for vote in step4_votes:
            src_id = vote["src"]
            src_info = get_node_topology(src_id)
            dst_id = vote["dst"]
            
            if src_info["role"] == "member":
                gl_id = src_info["parent_id"]
                step4a.append({"src": src_id, "dst": gl_id, "value": vote["value"], "type": "vote", "phase": "pre-commit"})
            elif src_info["role"] == "group_leader" and dst_id == historical_leader_id:
                # Group Leader 投票给 Root（使用历史 Leader ID）
                step4b.append({"src": src_id, "dst": dst_id, "value": vote["value"], "type": "vote", "phase": "pre-commit"})
        
        if step4a:
            animation_sequence.append(step4a)
        if step4b:
            animation_sequence.append(step4b)
    else:
        if step4_votes:
            animation_sequence.append(step4_votes)

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
            
            if is_double_layer:
                step5a: List[Dict[str, Any]] = []
                step5b: List[Dict[str, Any]] = []
                
                for dst in range(n):
                    if dst == src:
                        continue
                    dst_info = get_node_topology(dst)
                    if dst_info["role"] == "group_leader":
                        step5a.append({"src": src, "dst": dst, "value": value, "type": "qc", "dst_type": "group_leaders"})
                    elif dst_info["role"] == "member":
                        gl_id = dst_info["parent_id"]
                        step5b.append({"src": gl_id, "dst": dst, "value": value, "type": "qc", "dst_type": "group_members"})
                
                if step5a:
                    animation_sequence.append(step5a)
                if step5b:
                    animation_sequence.append(step5b)
            else:
                if msg.get("to") == "all":
                    for dst in range(n):
                        if dst != src and is_connection_allowed(src, dst, n, topology, branch_count):
                            step5_anim.append({"src": src, "dst": dst, "value": value, "type": "qc"})
                if step5_anim:
                    animation_sequence.append(step5_anim)

    # Step 6: Commit Vote (All -> Leader) [Phase: Commit]
    step6_votes: List[Dict[str, Any]] = []
    for msg in round_votes:
        if msg.get("phase") == "commit":
            m = {"src": msg["from"], "dst": msg["to"], "value": msg.get("value"), "type": "vote", "phase": "commit"}
            step6_votes.append(m)
            table_messages.append(m)
    
    if is_double_layer:
        step6a: List[Dict[str, Any]] = []
        step6b: List[Dict[str, Any]] = []
        
        for vote in step6_votes:
            src_id = vote["src"]
            src_info = get_node_topology(src_id)
            dst_id = vote["dst"]
            
            if src_info["role"] == "member":
                gl_id = src_info["parent_id"]
                step6a.append({"src": src_id, "dst": gl_id, "value": vote["value"], "type": "vote", "phase": "commit"})
            elif src_info["role"] == "group_leader" and dst_id == historical_leader_id:
                # Group Leader 投票给 Root（使用历史 Leader ID）
                step6b.append({"src": src_id, "dst": dst_id, "value": vote["value"], "type": "vote", "phase": "commit"})
        
        if step6a:
            animation_sequence.append(step6a)
        if step6b:
            animation_sequence.append(step6b)
    else:
        if step6_votes:
            animation_sequence.append(step6_votes)

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
            
            if is_double_layer:
                step7a: List[Dict[str, Any]] = []
                step7b: List[Dict[str, Any]] = []
                
                for dst in range(n):
                    if dst == src:
                        continue
                    dst_info = get_node_topology(dst)
                    if dst_info["role"] == "group_leader":
                        step7a.append({"src": src, "dst": dst, "value": value, "type": "qc", "dst_type": "group_leaders"})
                    elif dst_info["role"] == "member":
                        gl_id = dst_info["parent_id"]
                        step7b.append({"src": gl_id, "dst": dst, "value": value, "type": "qc", "dst_type": "group_members"})
                
                if step7a:
                    animation_sequence.append(step7a)
                if step7b:
                    animation_sequence.append(step7b)
            else:
                if msg.get("to") == "all":
                    for dst in range(n):
                        if dst != src and is_connection_allowed(src, dst, n, topology, branch_count):
                            step7_anim.append({"src": src, "dst": dst, "value": value, "type": "qc"})
                if step7_anim:
                    animation_sequence.append(step7_anim)

    # === 修复：从 consensus_history 中查找对应轮次的统计数据 ===
    round_consensus = "Consensus in progress..."
    complexity_comparison = None
    # 默认为空，避免显示当前正在进行的下一轮的即时数据（那样不准确）
    historical_network_stats = {}
    
    # 遍历历史记录找到对应轮次
    found_history = False
    for history in session.get("consensus_history", []):
        # 确保比较的是 int 类型
        if history.get("round") == round:
            found_history = True
            round_consensus = f"{history.get('status', 'Unknown')}: {history.get('description', '')}"
            if "stats" in history:
                stats_data = history["stats"]
                complexity_comparison = stats_data.get("complexity_comparison")
                historical_network_stats = stats_data.get("network_stats", {})
            break
    
    # (可选) 如果是查看刚刚完成的最新一轮，且还没写入 history（极少情况），可回退读取 consensus_result
    if not found_history and session.get("consensus_result"):
        # 简单校验一下 stats 是否存在
        if session["consensus_result"].get("stats"):
            # 这里不做严格 round 校验了，作为最后一道防线
            complexity_comparison = session["consensus_result"]["stats"].get("complexity_comparison")
            historical_network_stats = session["consensus_result"]["stats"].get("network_stats", {})
    
    return {
        "round": round,
        "leaderId": historical_leader_id,  # 返回历史时刻的 Leader ID
        "messages": table_messages,               # 表格数据（含phase，未拆分广播）
        "animation_sequence": animation_sequence, # 动画数据（支持分层，按步骤）
        "consensus": round_consensus,
        "nodeCount": config["nodeCount"],
        "topology": config["topology"],
        "proposalValue": config["proposalValue"],
        "stats": {
            "complexity_comparison": complexity_comparison,
            # 优先使用历史快照的 network_stats
            "network_stats": historical_network_stats if historical_network_stats else session.get("network_stats", {})
        } if complexity_comparison else None
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="127.0.0.1", port=8000)
