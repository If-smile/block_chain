"""
Socket.IO 事件处理和业务逻辑模块

此模块包含所有 Socket.IO 事件处理、消息处理和机器人逻辑。
从 main.py 重构而来，实现模块化设计。
"""

from typing import Dict, Any, Optional, List
import uuid
import random
import asyncio
from datetime import datetime

# 持久化模块
import database

# 导入全局状态和 Socket.IO 服务器
from state import sio, sessions, connected_nodes, node_sockets, get_session

# 导入共识算法函数
from consensus_engine import (
    get_quorum_threshold,
    get_local_quorum_threshold,
    get_next_phase,
    qc_extends,
    check_safe_node,
    update_node_locked_qc,
    update_node_prepare_qc,
    is_honest
)

# 导入拓扑管理函数
from topology_manager import (
    get_current_leader,
    get_topology_info,
    is_connection_allowed
)

# 导入数据模型
from models import SessionConfig, SessionInfo


# ==================== 网络辅助函数 ====================

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


# ==================== 会话管理 ====================

def create_session(config: SessionConfig) -> SessionInfo:
    """创建新的共识会话"""
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
        "current_view": 0,   # 当前视图编号（HotStuff，View 即时钟，核心逻辑使用此字段）
        "current_round": 1,  # 当前轮次编号（用于消息标记和历史回放，从1开始）
        "start_view_of_round": 0,  # 当前轮次的起始视图（用于统计 View Change 次数）
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
        "message_buffer": {},  # {view: [messages]} 未来视图的消息缓冲池（扁平结构）
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

    # 将初始会话状态持久化到 SQLite
    try:
        database.upsert_session(session_id, session)
    except Exception as e:
        print(f"[database] 保存初始会话 {session_id} 失败: {e}")
    
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


# ==================== Socket.IO 事件处理 ====================

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
        
        # 发送当前共识状态，确保新连接的节点能同步状态
        current_view = session.get("current_view", 0)
        current_phase = session.get("phase", "prepare")
        current_step = session.get("phase_step", 0)
        current_leader = session.get("leader_id", 0)
        
        await sio.emit('phase_update', {
            "phase": current_phase,
            "step": current_step,
            "leader": current_leader,
            "view": current_view
        }, room=sid)
        
        print(f"节点 {node_id} 同步状态: View={current_view}, Phase={current_phase}, Step={current_step}, Leader={current_leader}")
        
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
    """处理准备消息（双层 HotStuff：根据角色发送给上级）"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    value = data.get('value')
    
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    
    # 获取节点拓扑信息，确定投票目标
    node_info = get_topology_info(session, node_id, current_view)
    target_id = node_info['parent_id']
    
    # 如果是 Root (Global Leader)，不需要给自己投票
    if node_info['role'] == 'root':
        print(f"[双层 HotStuff] Global Leader {node_id} 不需要给自己投票")
        return
    
    target_sid = node_sockets.get(session_id, {}).get(target_id)
    
    # 构造投票（VOTE）消息，发送给上级（Group Leader 或 Global Leader）
    current_round = session.get("current_round", 1)
    vote_message = {
        "from": node_id,
        "to": target_id,
        "type": "vote",
        "value": value,
        "phase": "prepare",
        "view": current_view,
        "round": current_round,  # 使用当前轮次标记消息
        "qc": data.get("qc"),
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "byzantine": data.get("byzantine", False)
    }
    
    session["messages"]["vote"].append(vote_message)
    
    # 单播给上级（不广播）——无论目标是否在线，都计入一次消息发送
    count_message_sent(session_id, is_broadcast=False)
    if target_sid:
        if should_deliver_message(session_id):
            await sio.emit('message_received', vote_message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[双层 HotStuff] 节点 {node_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE(prepare)")
        else:
            print(f"[网络模拟] 节点 {node_id} 的 VOTE(prepare) 消息被丢弃 (目标: {target_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    else:
        print(f"[双层 HotStuff] 目标 {target_id} 不在线，缓存 VOTE")
    
    # 直接在后端处理投票累积
    await handle_vote(session_id, vote_message)

@sio.event
async def send_commit(sid, data):
    """处理提交消息（双层 HotStuff：根据角色发送给上级）"""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    value = data.get('value')
    
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    
    # 获取节点拓扑信息，确定投票目标
    node_info = get_topology_info(session, node_id, current_view)
    target_id = node_info['parent_id']
    
    # 如果是 Root (Global Leader)，不需要给自己投票
    if node_info['role'] == 'root':
        print(f"[双层 HotStuff] Global Leader {node_id} 不需要给自己投票")
        return
    
    target_sid = node_sockets.get(session_id, {}).get(target_id)
    
    # 构造投票（VOTE）消息，发送给上级（Group Leader 或 Global Leader）
    current_round = session.get("current_round", 1)
    vote_message = {
        "from": node_id,
        "to": target_id,
        "type": "vote",
        "value": value,
        "phase": "commit",
        "view": current_view,
        "round": current_round,  # 使用当前轮次标记消息
        "qc": data.get("qc"),
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "byzantine": data.get("byzantine", False)
    }
    
    session["messages"]["vote"].append(vote_message)
    
    # 单播给上级（不广播）——无论目标是否在线，都计入一次消息发送
    count_message_sent(session_id, is_broadcast=False)
    if target_sid:
        if should_deliver_message(session_id):
            await sio.emit('message_received', vote_message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[双层 HotStuff] 节点 {node_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE(commit)")
        else:
            print(f"[网络模拟] 节点 {node_id} 的 VOTE(commit) 消息被丢弃 (目标: {target_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    else:
        print(f"[双层 HotStuff] 目标 {target_id} 不在线，缓存 VOTE")
    
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
        "view": session.get("current_view", 0),  # HotStuff视图（核心逻辑使用）
        "round": session.get("current_round", 1),  # 使用当前轮次标记消息（用于历史过滤和前端展示）
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
    
    # 根据消息类型决定发送范围（双层 HotStuff：投票根据角色发送给上级）
    if message_type == "vote":
        current_view = session.get("current_view", 0)
        
        # 获取节点拓扑信息，确定投票目标（双层结构）
        node_info = get_topology_info(session, node_id, current_view)
        target_id = node_info['parent_id']
        
        # 如果是 Root (Global Leader)，不需要给自己投票
        if node_info['role'] == 'root':
            print(f"[双层 HotStuff] Global Leader {node_id} 不需要给自己投票")
            return
        
        # 更新消息的目标
        message["to"] = target_id
        
        target_sid = node_sockets.get(session_id, {}).get(target_id)
        # 单播给上级（不广播）——无论目标是否在线，都计入一次消息发送
        count_message_sent(session_id, is_broadcast=False)
        if target_sid:
            await sio.emit('message_received', message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[双层 HotStuff] 节点 {node_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE")
        else:
            print(f"[双层 HotStuff] 目标 {target_id} 不在线，缓存 VOTE")
        await handle_vote(session_id, message)
    else:
        # 其他消息默认广播给所有节点
        if should_deliver_message(session_id):
            await sio.emit('message_received', message, room=session_id)
            print(f"节点 {node_id} 的消息已发送 (传达概率: {session['config'].get('messageDeliveryRate', 100)}%)")
        else:
            print(f"节点 {node_id} 的消息被丢弃 (传达概率: {session['config'].get('messageDeliveryRate', 100)}%)")

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


# ==================== 消息处理函数 ====================

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
        await finalize_consensus(session_id, "Consensus Success", f"View {view} consensus reached")
        return

    # 遍历机器人节点，根据双层结构发送下一阶段投票（pre-commit / commit）
    for robot_id in session.get("robot_nodes", []):
        if robot_id == leader_id:
            # Global Leader 一般不再给自己单独发 vote 消息
            continue

        # 获取节点拓扑信息，确定投票目标
        node_info = get_topology_info(session, robot_id, view)
        target_id = node_info['parent_id']
        
        # 如果是 Root (Global Leader)，不需要给自己投票
        if node_info['role'] == 'root':
            continue

        current_round = session.get("current_round", 1)
        vote_msg: Dict[str, Any] = {
            "from": robot_id,
            "to": target_id,
            "type": "vote",
            "value": value,
            "phase": phase,              # 此处为新的阶段：pre-commit / commit
            "view": view,
            "round": current_round,  # 使用当前轮次标记消息
            "timestamp": datetime.now().isoformat(),
            "tampered": False,
            "isRobot": True
        }

        # 写入会话消息历史
        session["messages"]["vote"].append(vote_msg)

        # 发送给上级对应的 socket（双层结构：Member -> Group Leader, Group Leader -> Global Leader）
        target_sid = node_sockets.get(session_id, {}).get(target_id)
        if target_sid:
            await sio.emit("message_received", vote_msg, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[双层 HotStuff] 机器人节点 {robot_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE({phase})")

        # 交给双层 HotStuff 投票聚合逻辑处理
        await handle_vote(session_id, vote_msg)


async def handle_proposal_message(session_id: str, proposal_msg: Dict[str, Any], node_id: int) -> bool:
    """
    处理 Replica 节点收到的 Proposal 消息（HotStuff PRE-PREPARE）
    
    执行 SafeNode 谓词检查，如果通过则发送 Prepare Vote
    
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
    current_view = session["current_view"]
    
    # 如果 Proposal 的 view 大于当前 view，需要缓冲（消息缓冲机制）
    if proposal_view > current_view:
        print(f"节点 {node_id}: Proposal 视图 {proposal_view} > 当前视图 {current_view}，缓冲消息")
        buffer = session.setdefault("message_buffer", {})
        if node_id not in buffer:
            buffer[node_id] = {}
        if proposal_view not in buffer[node_id]:
            buffer[node_id][proposal_view] = []
        buffer[node_id][proposal_view].append({"type": "proposal", "msg": proposal_msg})
        return False
    
    # 如果 Proposal 的 view 小于当前 view，忽略旧消息
    if proposal_view < current_view:
        print(f"节点 {node_id}: 忽略旧 Proposal（View {proposal_view} < 当前 View {current_view}）")
        return False
    
    # 验证消息来自当前视图的 Leader（HotStuff 星型拓扑要求）
    leader_id = get_current_leader(session, proposal_view)
    if proposer_id != leader_id:
        print(f"节点 {node_id}: 拒绝 Proposal（来自非 Leader {proposer_id}，当前 Leader 是 {leader_id}）")
        return False
    
    # HotStuff SafeNode 谓词检查（Safety 的核心机制）
    if not check_safe_node(session, node_id, proposal_view, proposal_value, proposal_qc):
        print(f"节点 {node_id}: SafeNode 检查失败，拒绝 Proposal（View {proposal_view}）")
        return False
    
    # 通过 SafeNode 检查，节点发送 Prepare Vote
    print(f"节点 {node_id}: SafeNode 检查通过，发送 Vote（View {proposal_view}, Value {proposal_value}）")
    
    # 完善封装逻辑：SafeNode 检查通过后，触发投票动作
    # 仅对机器人节点自动发送投票，人类节点通过 WebSocket 事件由前端发送
    if node_id in session.get("robot_nodes", []):
        await handle_robot_prepare(session_id, node_id, proposal_value)
        return True
    else:
        # 人类节点：通过 WebSocket 事件通知前端发送 Vote
        # 这里返回 True 表示可以通过 SafeNode 检查，前端可以发送 Vote
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
    双层 HotStuff 投票处理：支持分层投票聚合
    
    流程:
    1. Member -> Group Leader: 普通节点投票给组内 Leader
    2. Group Leader -> Global Leader: 组内达到阈值后，Group Leader 发送 GroupVote（权重票）
    3. Global Leader: 收集 GroupVote，检查总权重阈值，生成最终 QC
    
    支持消息缓冲：如果 view > current_view，消息会被缓冲，等视图切换后再处理
    """
    session = get_session(session_id)
    if not session:
        return
    
    view = vote_message.get("view", session.get("current_view", 0))
    phase = vote_message.get("phase", "prepare")
    voter = vote_message.get("from")
    value = vote_message.get("value")
    current_view = session["current_view"]
    is_group_vote = vote_message.get("is_group_vote", False)  # 是否为 GroupVote（聚合票）
    vote_weight = vote_message.get("weight", 1)  # 投票权重（GroupVote 的权重 > 1）
    
    # 如果投票的 view 大于当前 view，缓冲消息（消息缓冲机制）
    if view > current_view:
        print(f"投票视图 {view} > 当前视图 {current_view}，缓冲消息")
        buffer = session.setdefault("message_buffer", {})
        if view not in buffer:
            buffer[view] = []
        buffer[view].append(vote_message)
        return
    
    # 如果投票的 view 小于当前 view，忽略旧消息
    if view < current_view:
        print(f"忽略旧投票（View {view} < 当前 View {current_view}）")
        return
    
    # 获取投票者的拓扑信息
    voter_info = get_topology_info(session, voter, view)
    voter_role = voter_info['role']
    target_id = vote_message.get("to")
    
    # ========== Case A: Member 投票给 Group Leader ==========
    if voter_role == 'member':
        group_leader_id = voter_info['parent_id']
        if target_id != group_leader_id:
            print(f"Member {voter} 投票目标错误（目标: {target_id}, 应为 Group Leader: {group_leader_id}），忽略")
            return
        
        # 存储到组内投票池
        key = (view, phase, value, group_leader_id)  # 添加 group_leader_id 区分不同组
        pending_group_votes = session.setdefault("pending_group_votes", {})
        group_voters = pending_group_votes.setdefault(key, set())
        group_voters.add(voter)
        
        # 检查组内阈值
        group_size = voter_info['group_size']
        local_threshold = get_local_quorum_threshold(session, group_size)
        
        if len(group_voters) < local_threshold:
            print(f"[双层 HotStuff] Group Leader {group_leader_id} 收到组员 {voter} 投票: phase={phase}, view={view}, 组内累积 {len(group_voters)}/{local_threshold}")
            return
        
        # 组内达到阈值，Group Leader 生成 GroupVote 发送给 Global Leader
        print(f"[双层 HotStuff] Group Leader {group_leader_id} 收到组内 {len(group_voters)} 票（阈值 {local_threshold}），生成 GroupVote 发送给 Global Leader")
        
        global_leader_id = get_current_leader(session, view)
        current_round = session.get("current_round", 1)
        group_vote_message = {
            "from": group_leader_id,
            "to": global_leader_id,
            "type": "vote",
            "value": value,
            "phase": phase,
            "view": view,
            "round": current_round,  # 使用当前轮次标记消息
            "is_group_vote": True,  # 标记为 GroupVote
            "weight": len(group_voters),  # 权重 = 组内投票数
            "group_id": voter_info['group_id'],
            "group_voters": list(group_voters),  # 记录组内投票者（用于统计）
            "timestamp": datetime.now().isoformat()
        }
        
        session["messages"]["vote"].append(group_vote_message)
        
        # 发送给 Global Leader
        global_leader_sid = node_sockets.get(session_id, {}).get(global_leader_id)
        if global_leader_sid:
            if should_deliver_message(session_id):
                await sio.emit('message_received', group_vote_message, room=global_leader_sid)
                print(f"[双层 HotStuff] Group Leader {group_leader_id} 向 Global Leader {global_leader_id} 发送 GroupVote (权重={len(group_voters)})")
            else:
                print(f"[网络模拟] Group Leader {group_leader_id} 的 GroupVote 消息被丢弃 (目标: Global Leader {global_leader_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
        
        # 递归处理 GroupVote（作为 Global Leader 收到的投票）
        await handle_vote(session_id, group_vote_message)
        return
    
    # ========== Case B: Group Leader 投票给 Global Leader（或 Global Leader 自己投票） ==========
    global_leader_id = get_current_leader(session, view)
    
    # 验证投票目标
    if voter_role == 'group_leader':
        if target_id != global_leader_id:
            print(f"Group Leader {voter} 投票目标错误（目标: {target_id}, 应为 Global Leader: {global_leader_id}），忽略")
            return
    elif voter_role == 'root':
        # Global Leader 自己也可以投票（但通常不需要）
        if target_id != global_leader_id:
            print(f"Global Leader {voter} 投票目标错误，忽略")
            return
    else:
        print(f"未知角色 {voter_role} 的投票，忽略")
        return
    
    # Global Leader 收集投票（包括 GroupVote 和直接投票）
    key = (view, phase, value)
    pending = session.setdefault("pending_votes", {})
    
    # 如果是 GroupVote，累加权重；否则权重为 1
    if is_group_vote:
        # GroupVote: 累加权重
        if key not in pending:
            pending[key] = {"total_weight": 0, "group_votes": []}
        pending[key]["total_weight"] += vote_weight
        pending[key]["group_votes"].append({
            "from": voter,
            "weight": vote_weight,
            "group_voters": vote_message.get("group_voters", [])
        })
        print(f"[双层 HotStuff] Global Leader {global_leader_id} 收到 Group Leader {voter} 的 GroupVote (权重={vote_weight}), 总权重={pending[key]['total_weight']}")
    else:
        # 直接投票（权重为 1）
        if key not in pending:
            pending[key] = {"total_weight": 0, "group_votes": []}
        pending[key]["total_weight"] += 1
        pending[key]["group_votes"].append({
            "from": voter,
            "weight": 1,
            "group_voters": [voter]
        })
        print(f"[双层 HotStuff] Global Leader {global_leader_id} 收到节点 {voter} 的直接投票, 总权重={pending[key]['total_weight']}")
    
    # ========== 防止重复处理：检查当前会话的 phase 是否已经翻篇 ==========
    current_session_phase = session.get("phase", "prepare")
    if phase != current_session_phase:
        print(f"[防重复] 投票的 phase ({phase}) 与当前会话 phase ({current_session_phase}) 不匹配，忽略（该阶段已完成或尚未开始）")
        return
    
    # 检查全局阈值（基于权重）
    threshold = get_quorum_threshold(session)
    total_weight = pending[key]["total_weight"]
    
    if total_weight < threshold:
        print(f"[双层 HotStuff] 投票累积中: phase={phase}, view={view}, 总权重 {total_weight}/{threshold}")
        return
    
    # 达到阈值，生成 QC
    # 收集所有投票者（从 GroupVote 中提取）
    all_voters = set()
    for gv in pending[key]["group_votes"]:
        all_voters.update(gv.get("group_voters", [gv["from"]]))
    
    qc = {
        "phase": phase,
        "view": view,
        "signers": list(all_voters),
        "value": value,
        "total_weight": total_weight,  # 记录总权重
        "is_multi_layer": True  # 标记为双层结构
    }
    
    next_phase = get_next_phase(phase)
    session["phase"] = next_phase
    session["phase_step"] += 1
    
    current_round = session.get("current_round", 1)
    qc_message = {
        "from": global_leader_id,
        "to": "group_leaders",  # 双层结构：只发给 Group Leaders
        "type": "qc",
        "phase": phase,
        "next_phase": next_phase,
        "view": view,
        "round": current_round,  # 使用当前轮次标记消息
        "qc": qc,
        "timestamp": datetime.now().isoformat()
    }
    
    # 将完整的 QC 广播消息写入会话历史
    session["messages"]["qc"].append(qc_message)
    
    # ========== 双层广播：Global Leader -> Group Leaders -> Members ==========
    n = session["config"]["nodeCount"]
    branch_count = session["config"].get("branchCount", 2)
    group_size = max(1, n // branch_count)
    
    # 第一步：Global Leader 发送给所有 Group Leaders
    group_leaders = []
    for gid in range(branch_count):
        group_start_id = gid * group_size
        if group_start_id < n and group_start_id != global_leader_id:  # 排除 Global Leader 自己
            group_leaders.append(group_start_id)
    
    # 发送给 Group Leaders（逻辑上发送给所有 Group Leaders）
    if group_leaders:
        count_message_sent(session_id, is_broadcast=False, target_count=len(group_leaders))
    for gl_id in group_leaders:
        gl_sid = node_sockets.get(session_id, {}).get(gl_id)
        if gl_sid:
            if should_deliver_message(session_id):
                await sio.emit('message_received', qc_message, room=gl_sid)
            else:
                print(f"[网络模拟] QC 消息被丢弃 (目标: Group Leader {gl_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    
    # 第二步：Group Leaders 转发给组内 Members（按组统计目标成员数）
    for gl_id in group_leaders:
        gl_info = get_topology_info(session, gl_id, view)
        group_id = gl_info['group_id']
        group_start_id = group_id * group_size
        group_end_id = min((group_id + 1) * group_size, n)
        
        # Group Leader 转发给组内所有 Members
        forward_message = qc_message.copy()
        forward_message["from"] = gl_id
        forward_message["to"] = "group_members"
        
        # 逻辑目标成员总数（不依赖 member_sid）
        target_member_count = max(group_end_id - (group_start_id + 1), 0)
        if target_member_count > 0:
            count_message_sent(session_id, is_broadcast=False, target_count=target_member_count)
        
        for member_id in range(group_start_id + 1, group_end_id):  # +1 因为 Group Leader 自己不需要转发
            member_sid = node_sockets.get(session_id, {}).get(member_id)
            if member_sid:
                if should_deliver_message(session_id):
                    await sio.emit('message_received', forward_message, room=member_sid)
                else:
                    print(f"[网络模拟] QC 转发消息被丢弃 (目标: Member {member_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    
    # 也发送给所有节点（用于前端展示，但实际路由是分层的）
    await sio.emit('message_received', qc_message, room=session_id)
    
    await sio.emit('phase_update', {
        "phase": next_phase,
        "step": session["phase_step"],
        "leader": global_leader_id,
        "view": view
    }, room=session_id)
    
    print(f"[双层 HotStuff] Global Leader {global_leader_id} 收到总权重 {total_weight}（阈值 {threshold}），生成 {phase} QC 并进入 {next_phase} 阶段（View {view}）")
    print(f"[双层 HotStuff] QC 通过分层广播：Global Leader -> {len(group_leaders)} Group Leaders -> Members")
    
    # 通知所有节点处理 QC（更新 prepareQC/lockedQC）
    for node_id in range(n):
        await handle_qc_message(session_id, qc_message, node_id)
    
    # 清理已处理的投票
    pending[key] = {"total_weight": total_weight, "group_votes": pending[key]["group_votes"]}

    # HotStuff 多阶段自动推进：在进入下一阶段后，调度机器人自动投票
    # next_phase 可能是 pre-commit / commit / decide
    if next_phase == "decide":
        # Decide 阶段完成，达成共识
        await finalize_consensus(session_id, "Consensus Success", f"View {view} consensus reached")
    else:
        try:
            asyncio.create_task(trigger_robot_votes(session_id, view, next_phase, value))
        except RuntimeError as e:
            print(f"调度 trigger_robot_votes 失败: {e}")


# ==================== 共识逻辑 ====================

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
        await finalize_consensus(session_id, "Consensus Success", f"Received {len(correct_nodes)} valid messages")
    elif len(error_nodes) >= f + 1:  # 包括自己，需要f+1个错误消息
        print(f"共识失败 - 收到{len(error_nodes)}个错误消息（需要{f+1}个）")
        print(f"发送共识结果: 共识失败")
        await finalize_consensus(session_id, "Consensus Failed", f"Received {len(error_nodes)} invalid messages")
    else:
        print(f"提交阶段等待中 - 正确消息:{len(correct_nodes)}, 错误消息:{len(error_nodes)}")

async def finalize_consensus(session_id: str, status: str = "Consensus Completed", description: str = "Consensus completed"):
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
    session["phase_step"] = 4  # Fix: Set to 4 to match frontend 100% progress (4 steps total)
    session["status"] = "completed"
    
    config = session["config"]
    
    # ================= 通信复杂度统计报告（4种算法对比） =================
    network_stats = session.get("network_stats", {})
    actual_messages = network_stats.get("total_messages_sent", 0)
    n = config["nodeCount"]
    branch_count = config.get("branchCount", 2)  # 分组数 K（可能为 0 或负数，后面统一归一化）
    
    # 边界处理：确保 K >= 1，并计算分组大小
    k = max(1, branch_count)
    group_size = n // k if k > 0 else n
    
    # ========== 影子计算 (Shadow Calculation)：基于当前 n、k 的“推演实际值” ==========
    # 1. Shadow PBFT: 全网广播（这里只考虑 Prepare + Commit 两个阶段）
    shadow_pbft_actual = 2 * n * (n - 1)
    
    # 2. Shadow Pure HotStuff: 星型广播（4 个阶段，每阶段 2×(N-1) 条消息）
    #    4 * (Leader 广播 + 节点回复)
    shadow_hotstuff_actual = 8 * (n - 1)
    
    # 3. Shadow Multi-Layer PBFT: 分层全网广播
    #    顶层：K 个组长之间 PBFT -> 2 * K * (K - 1)
    #    底层：K 个组，每组 group_size 个节点 -> K * 2 * group_size * (group_size - 1)
    shadow_multilayer_actual = (2 * k * (k - 1)) + (k * 2 * group_size * (group_size - 1))
    
    # ========== 计算4种算法的理论消息数 (Theoretical) ==========
    
    # Double-Layer HotStuff (本系统) 理论值：4阶段 * 2层 * N
    hotstuff_double_actual = actual_messages
    theoretical_double_hotstuff = 8 * n
    
    # 传统 PBFT (Pure PBFT) - O(N^2)
    theoretical_pbft = 2 * n * n
    
    # 传统 HotStuff (Pure HotStuff) - O(N)
    theoretical_hotstuff = 4 * n
    
    # 双层 PBFT (Multi-Layer PBFT) - 分层 PBFT: O(K² + N²/K)
    theoretical_multilayer = 2 * k * k + 2 * n * n // k
    
    # ========== 计算优化倍数 ==========
    # 双层 HotStuff 相对于其他算法的优化倍数（基于理论值）
    optimization_vs_pbft_pure = theoretical_pbft / hotstuff_double_actual if hotstuff_double_actual > 0 else 0.0
    optimization_vs_hotstuff_pure = theoretical_hotstuff / hotstuff_double_actual if hotstuff_double_actual > 0 else 0.0
    optimization_vs_pbft_multi = theoretical_multilayer / hotstuff_double_actual if hotstuff_double_actual > 0 else 0.0
    
    # ========== 构建复杂度对比数据 ==========
    complexity_comparison = {
        "double_hotstuff": {
            "name": "Double-Layer HotStuff (System)",
            "theoretical": theoretical_double_hotstuff,
            "actual": hotstuff_double_actual,
            "complexity": "O(N)",
            "is_current": True
        },
        "pbft_pure": {
            "name": "PBFT (Pure)",
            "theoretical": theoretical_pbft,
            "actual": shadow_pbft_actual,
            "complexity": "O(N²)",
            "optimization_ratio": optimization_vs_pbft_pure
        },
        "hotstuff_pure": {
            "name": "HotStuff (Pure)",
            "theoretical": theoretical_hotstuff,
            "actual": shadow_hotstuff_actual,
            "complexity": "O(N)",
            "optimization_ratio": optimization_vs_hotstuff_pure
        },
        "pbft_multi_layer": {
            "name": "PBFT (Multi-Layer)",
            "theoretical": theoretical_multilayer,
            "actual": shadow_multilayer_actual,
            "complexity": "O(K² + N²/K)",
            "optimization_ratio": optimization_vs_pbft_multi
        }
    }
    
    # 创建共识结果
    consensus_result = {
        "status": status,
        "description": description,
        "stats": {
            "expected_nodes": config["nodeCount"],
            "expected_prepare_nodes": config["nodeCount"] - 1,
            "total_messages": len(session["messages"]["prepare"]) + len(session["messages"]["commit"]),
            "complexity_comparison": complexity_comparison,
            "network_stats": {
                "actual_messages": actual_messages,
                "node_count": n,
                "branch_count": branch_count
            }
        }
    }
    
    session["consensus_result"] = consensus_result
    
    # ========== 打印详细报告 ==========
    print("\n" + "=" * 80)
    print("📊 共识算法通信复杂度对比分析报告")
    print("=" * 80)
    print("-" * 80)
    print(f"[统计说明]")
    current_round = session.get("current_round", 1)
    start_view = session.get("start_view_of_round", 0)
    current_view = session.get("current_view", 0)
    view_change_count = max(0, current_view - start_view)
    print(f"  • 当前轮次 (Round): {current_round}")
    print(f"  • 经历视图 (Views): {current_view} (View Change 次数: {view_change_count})")
    print(f"  • 统计范围: 从 Pre-Prepare 到 Decide 的完整共识周期")
    print(f"  • 注意: 本系统演示的是 Basic HotStuff (分阶段提交)。")
    print(f"         如果是 Chained HotStuff (流水线模式)，")
    print(f"         Prepare QC 同时也是下一视图的 Pre-Prepare 消息，")
    print(f"         其摊还通信复杂度会进一步降低。")
    print("-" * 80)
    print(f"[配置] 节点总数 N = {n}, 分组数 K = {branch_count}")
    print(f"[实测] 双层 HotStuff 实际消息数: {hotstuff_double_actual}")
    print("-" * 80)
    print(f"[算法对比] (Theoretical vs Actual/Shadow)")
    print(f"{'算法':<28}{'Theoretical':>16}{'Actual/Shadow':>18}{'复杂度':>12}")
    print("-" * 80)
    print(f"{'Double-Layer HotStuff':<28}{theoretical_double_hotstuff:>16}{hotstuff_double_actual:>18}{'O(N)':>12}")
    print(f"{'PBFT (Pure)':<28}{theoretical_pbft:>16}{shadow_pbft_actual:>18}{'O(N²)':>12}")
    print(f"{'HotStuff (Pure)':<28}{theoretical_hotstuff:>16}{shadow_hotstuff_actual:>18}{'O(N)':>12}")
    print(f"{'PBFT (Multi-Layer)':<28}{theoretical_multilayer:>16}{shadow_multilayer_actual:>18}{'O(K²+N²/K)':>12}")
    print("-" * 80)
    if hotstuff_double_actual > 0:
        print(f"[优化倍数] 双层 HotStuff 相对于:")
        print(f"  • 传统 PBFT:        {optimization_vs_pbft_pure:>8.2f}x")
        print(f"  • 传统 HotStuff:    {optimization_vs_hotstuff_pure:>8.2f}x")
        print(f"  • 双层 PBFT:        {optimization_vs_pbft_multi:>8.2f}x")
        print(f"💡 双层结构优势: 通过分组聚合，Global Leader 只需处理 K 个 GroupVote，")
        print(f"   而不是 N 个单独投票，显著降低了全局 Leader 的通信压力")
    else:
        print("⚠️  警告: 未统计到任何共识消息，无法计算优化倍数")
    print("=" * 80 + "\n")
    
    # 广播共识结果
    print(f"准备发送共识结果: {consensus_result}")
    await sio.emit('consensus_result', consensus_result, room=session_id)
    print(f"已发送共识结果到房间: {session_id}")
    
    # 更新阶段
    await sio.emit('phase_update', {
        "phase": "completed",
        "step": 4,  # Fix: Set to 4 to match frontend 100% progress
        "isMyTurn": False
    }, room=session_id)
    
    print(f"会话 {session_id} View {session['current_view']} 共识完成: {status}")
    
    # 保存共识历史（使用 round 和 view 作为标识，包含完整的 stats 数据）
    current_round = session.get("current_round", 1)
    history_item = {
        "round": current_round,
        "view": session["current_view"],
        "status": status,
        "description": description,
        "stats": consensus_result.get("stats"),  # 保存完整的统计数据，包括 complexity_comparison 和 network_stats
        "timestamp": datetime.now().isoformat()
    }
    session["consensus_history"].append(history_item)

    # 将最新历史记录和会话状态持久化
    try:
        database.append_history(session_id, history_item)
        database.upsert_session(session_id, session)
    except Exception as e:
        print(f"[database] 保存共识历史/会话状态失败: session_id={session_id}, error={e}")
    
    # HotStuff 中，一次共识完成不代表需要"下一轮"
    # 如果需要继续共识，应该通过 New-View 机制开始新的 View
    # 这里我们保持会话状态为 completed，不再自动启动下一轮
    print(f"View {session['current_view']} 共识完成，会话状态设为 completed")
    
    # 开启自动多轮演示模式：10秒后开始下一轮
    print(f"当前轮次共识完成，10秒后自动开始下一轮...")
    asyncio.create_task(start_next_round(session_id))

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

async def process_message_buffer(session_id: str, view: int):
    """
    处理消息缓冲池：取出指定视图的缓冲消息并重新处理（消息缓冲机制）
    
    参数:
        session_id: 会话ID
        view: 要处理的视图号
    """
    session = get_session(session_id)
    if not session:
        return
    
    buffer = session.get("message_buffer", {})
    if not buffer:
        return
    
    print(f"处理 View {view} 的缓冲消息...")
    
    # 遍历所有节点的缓冲消息
    for node_id, node_buffer in buffer.items():
        if view not in node_buffer:
            continue
        
        messages = node_buffer[view]
        print(f"节点 {node_id} 的 View {view} 缓冲中有 {len(messages)} 条消息")
        
        # 处理每条缓冲消息
        for buffered_msg in messages:
            msg_type = buffered_msg.get("type")
            msg = buffered_msg.get("msg")
            
            if msg_type == "proposal":
                # 重新处理 Proposal 消息
                await handle_proposal_message(session_id, msg, node_id)
            elif msg_type == "vote":
                # 重新处理 Vote 消息
                await handle_vote(session_id, msg)
        
        # 清除已处理的消息
        del node_buffer[view]
    
    print(f"View {view} 的缓冲消息处理完成")

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
    
    # ========== 重置所有机器人节点的投票状态（修复 Timeout Loop） ==========
    # 在视图切换时，必须重置机器人的 sent_prepare/sent_commit 标志
    # 否则机器人会误以为自己在新 View 中已投票，导致拒绝再次投票
    print(f"[View Change] 重置所有机器人节点的投票状态...")
    for robot_id in session.get("robot_nodes", []):
        if robot_id not in session["robot_node_states"]:
            session["robot_node_states"][robot_id] = {}
        
        session["robot_node_states"][robot_id] = {
            "received_pre_prepare": False,
            "received_prepare_count": 0,
            "received_commit_count": 0,
            "sent_prepare": False,  # 关键：重置此标志，允许在新 View 中重新投票
            "sent_commit": False
        }
        print(f"  机器人节点 {robot_id}: 投票状态已重置")
    
    # 所有节点发送 NEW-VIEW 消息给 Next Leader
    for node_id in range(n):
        node_state = session["node_states"].get(node_id, {})
        highQC = node_state.get("highQC")  # 节点最高的 prepareQC
        
        current_round = session.get("current_round", 1)
        new_view_msg = {
            "from": node_id,
            "to": next_leader_id,
            "type": "new_view",
            "view": new_view,
            "old_view": old_view,
            "round": current_round,  # 使用当前轮次标记消息
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
                if should_deliver_message(session_id):
                    await sio.emit('message_received', new_view_msg, room=node_sid)
                else:
                    print(f"[网络模拟] 节点 {node_id} 的 NEW-VIEW 消息被丢弃 (目标: Next Leader {next_leader_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
        
        # Leader 收集 NEW-VIEW 消息
        if node_id == next_leader_id:
            continue  # Leader 不给自己发送
        
        pending_new_views = session.setdefault("pending_new_views", {})
        if new_view not in pending_new_views:
            pending_new_views[new_view] = {}
        pending_new_views[new_view][node_id] = new_view_msg
        
        # 统计每个节点发送给 Leader 的 NEW-VIEW 消息（包含机器人和人类）
        count_message_sent(session_id, is_broadcast=False)
    
    # 通知所有节点进入 New-View 阶段
    await sio.emit('phase_update', {
        "phase": "new-view",
        "step": 0,
        "leader": next_leader_id,
        "view": new_view
    }, room=session_id)
    
    # Next Leader 检查是否已收集到足够的 NEW-VIEW 消息并开始新视图共识
    await start_new_view_consensus(session_id, new_view)
    
    # 处理消息缓冲池：取出当前新 View 的消息并重新处理（消息缓冲机制）
    # 注意：在视图切换完成后处理缓冲消息，确保消息在正确的视图上下文中处理
    buffer = session.get("message_buffer", {})
    if new_view in buffer:
        buffered_votes = buffer[new_view]
        print(f"View {new_view} 缓冲中有 {len(buffered_votes)} 条投票消息，开始重新处理")
        for vote_msg in buffered_votes:
            await handle_vote(session_id, vote_msg)
        # 清除已处理的消息
        del buffer[new_view]

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
    # 记录本轮次的起始视图，用于统计 View Change 次数
    session["start_view_of_round"] = session["current_view"]
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
    
    # 节点状态持久化：保持 robot_nodes 和 human_nodes 列表不变
    # 如果用户在第一轮选择了"Normal Consensus (托管给机器人)"或保持"Human Mode"，
    # 这个状态必须在后续轮次继续保持，不要重置回默认状态
    print(f"第{current_round}轮开始 - 保持节点状态持久化")
    print(f"第{current_round}轮开始 - 当前机器人节点: {session['robot_nodes']}")
    print(f"第{current_round}轮开始 - 当前人类节点: {session['human_nodes']}")
    
    # 重置机器人节点状态（重置所有机器人节点的投票状态，但保持节点身份不变）
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

    # 持久化新一轮开始时的会话状态
    try:
        database.upsert_session(session_id, session)
    except Exception as e:
        print(f"[database] 保存新一轮会话状态失败: session_id={session_id}, error={e}")
    
    # 机器人提议者发送预准备消息（注意：HotStuff 中应该通过 View Change 继续，而不是"下一轮"）
    # 这里保留以兼容旧代码，但实际上应该通过 trigger_view_change 来继续共识
    await robot_send_pre_prepare(session_id, highQC=None)

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
    # 记录第一轮次的起始视图
    if "start_view_of_round" not in session:
        session["start_view_of_round"] = session["current_view"]
    
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
    
    # 发送 Proposal 消息（双层 HotStuff：Global Leader -> Group Leaders -> Members）
    current_round = session.get("current_round", 1)
    message = {
        "from": proposer_id,
        "to": "group_leaders",  # 双层结构：只发给 Group Leaders
        "type": "pre_prepare",
        "value": proposal_value,
        "phase": "prepare",  # HotStuff 中 Proposal 开启 Prepare 阶段
        "view": current_view,
        "round": current_round,  # 使用当前轮次标记消息
        "qc": highQC,  # 携带 HighQC（如果有）
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "isRobot": True
    }
    
    session["messages"]["pre_prepare"].append(message)
    
    # ========== 双层广播：Global Leader -> Group Leaders -> Members ==========
    n = config["nodeCount"]
    branch_count = config.get("branchCount", 2)
    group_size = max(1, n // branch_count)
    
    # 第一步：Global Leader 发送给所有 Group Leaders
    group_leaders = []
    for gid in range(branch_count):
        group_start_id = gid * group_size
        if group_start_id < n and group_start_id != proposer_id:  # 排除 Global Leader 自己
            group_leaders.append(group_start_id)
    
    # 发送给 Group Leaders（逻辑上发送给所有 Group Leaders）
    if group_leaders:
        count_message_sent(session_id, is_broadcast=False, target_count=len(group_leaders))
    for gl_id in group_leaders:
        gl_sid = node_sockets.get(session_id, {}).get(gl_id)
        if gl_sid:
            if should_deliver_message(session_id):
                await sio.emit('message_received', message, room=gl_sid)
            else:
                print(f"[网络模拟] Proposal 消息被丢弃 (目标: Group Leader {gl_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    
    # 第二步：Group Leaders 转发给组内 Members
    for gl_id in group_leaders:
        gl_info = get_topology_info(session, gl_id, current_view)
        group_id = gl_info['group_id']
        group_start_id = group_id * group_size
        group_end_id = min((group_id + 1) * group_size, n)
        
        # Group Leader 转发给组内所有 Members
        forward_message = message.copy()
        forward_message["from"] = gl_id
        forward_message["to"] = "group_members"
        
        # 逻辑目标成员总数（不依赖 member_sid）
        target_member_count = max(group_end_id - (group_start_id + 1), 0)
        if target_member_count > 0:
            count_message_sent(session_id, is_broadcast=False, target_count=target_member_count)
        
        for member_id in range(group_start_id + 1, group_end_id):  # +1 因为 Group Leader 自己不需要转发
            member_sid = node_sockets.get(session_id, {}).get(member_id)
            if member_sid:
                if should_deliver_message(session_id):
                    await sio.emit('message_received', forward_message, room=member_sid)
                else:
                    print(f"[网络模拟] Proposal 转发消息被丢弃 (目标: Member {member_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    
    # 也发送给所有节点（用于前端展示，但实际路由是分层的）
    await sio.emit('message_received', message, room=session_id)
    
    print(f"[双层 HotStuff] Global Leader {proposer_id} (View {current_view}) 发送了 Proposal 消息: value={proposal_value}, highQC.view={highQC.get('view') if highQC else None}")
    print(f"[双层 HotStuff] Proposal 通过分层广播：Global Leader -> {len(group_leaders)} Group Leaders -> Members")
    
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
    
    通过调用 handle_proposal_message 来执行 SafeNode 检查和投票逻辑（代码复用）
    """
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    
    # 找到最新的 Proposal 消息
    proposal_msgs = [m for m in session["messages"]["pre_prepare"] if m.get("view") == current_view]
    if not proposal_msgs:
        print(f"View {current_view}: 未找到 Proposal 消息，机器人节点不投票")
        return
    
    proposal_msg = proposal_msgs[-1]  # 取最新的
    
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
    
    # 所有机器人验证者（除了Leader）通过 handle_proposal_message 进行 SafeNode 检查并发送投票
    leader_id = get_current_leader(session, current_view)
    for robot_id in session.get("robot_nodes", []):
        if robot_id == leader_id:  # Leader不给自己投票
            continue
        
        if session["robot_node_states"][robot_id].get("sent_prepare"):
            continue  # 已经发送过了
        
        # 直接调用 handle_proposal_message 进行处理（激活死代码，复用逻辑）
        await handle_proposal_message(session_id, proposal_msg, robot_id)
        session["robot_node_states"][robot_id]["sent_prepare"] = True

async def handle_robot_prepare(session_id: str, robot_id: int, value: int):
    """
    处理机器人节点的 Prepare 阶段投票（双层 HotStuff：根据角色发送给上级）
    
    注意：此函数假设已经通过了 SafeNode 检查
    
    双层结构:
    - Member -> Group Leader
    - Group Leader -> Global Leader
    - Root (Global Leader) -> 自己处理（通常不需要投票）
    """
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    
    # 获取节点拓扑信息，确定投票目标
    node_info = get_topology_info(session, robot_id, current_view)
    target_id = node_info['parent_id']
    
    # 如果是 Root (Global Leader)，不需要给自己投票
    if node_info['role'] == 'root':
        print(f"[双层 HotStuff] Global Leader {robot_id} 不需要给自己投票")
        return
    
    target_sid = node_sockets.get(session_id, {}).get(target_id)
    
    current_round = session.get("current_round", 1)
    vote_message = {
        "from": robot_id,
        "to": target_id,
        "type": "vote",
        "value": value,
        "phase": "prepare",
        "view": current_view,
        "round": current_round,  # 使用当前轮次标记消息
        "qc": None,
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "isRobot": True
    }
    
    session["messages"]["vote"].append(vote_message)
    
    # 单播给上级（不广播）——无论目标是否在线，都计入一次消息发送
    count_message_sent(session_id, is_broadcast=False)
    if target_sid:
        if should_deliver_message(session_id):
            await sio.emit('message_received', vote_message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[双层 HotStuff] 机器人节点 {robot_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE(prepare) [View {current_view}]")
        else:
            print(f"[网络模拟] 机器人节点 {robot_id} 的 VOTE(prepare) 消息被丢弃 (目标: {target_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    else:
        print(f"[双层 HotStuff] 目标 {target_id} 不在线，缓存机器人投票")
    
    await handle_vote(session_id, vote_message)

async def schedule_robot_prepare(session_id: str, robot_id: int, value: int):
    """调度机器人节点在短暂延迟后发送准备阶段投票"""
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    # 短暂延迟，模拟网络延迟或让出初始化时间
    await asyncio.sleep(2.0)
    
    session = get_session(session_id)
    if not session:
        return
    
    # 检查视图是否改变
    if session["current_view"] != current_view:
        print(f"视图已改变（{current_view} -> {session['current_view']}），节点{robot_id}放弃发送准备消息")
        return
    
    # 检查阶段是否改变
    if session.get("phase") != "prepare":
        print(f"阶段已改变，节点{robot_id}放弃发送准备消息")
        return
    
    await handle_robot_prepare(session_id, robot_id, value)

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
    """处理机器人节点的提交阶段投票（双层 HotStuff：根据角色发送给上级）"""
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    
    # 获取节点拓扑信息，确定投票目标
    node_info = get_topology_info(session, robot_id, current_view)
    target_id = node_info['parent_id']
    
    # 如果是 Root (Global Leader)，不需要给自己投票
    if node_info['role'] == 'root':
        print(f"[双层 HotStuff] Global Leader {robot_id} 不需要给自己投票")
        return
    
    target_sid = node_sockets.get(session_id, {}).get(target_id)
    
    current_round = session.get("current_round", 1)
    vote_message = {
        "from": robot_id,
        "to": target_id,
        "type": "vote",
        "value": value,
        "phase": "commit",
        "view": current_view,
        "round": current_round,  # 使用当前轮次标记消息
        "qc": None,
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "isRobot": True
    }
    
    session["messages"]["vote"].append(vote_message)
    
    # 单播给上级（不广播）——无论目标是否在线，都计入一次消息发送
    count_message_sent(session_id, is_broadcast=False)
    if target_sid:
        if should_deliver_message(session_id):
            await sio.emit('message_received', vote_message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[双层 HotStuff] 机器人节点 {robot_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE(commit)")
        else:
            print(f"[网络模拟] 机器人节点 {robot_id} 的 VOTE(commit) 消息被丢弃 (目标: {target_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    else:
        print(f"[双层 HotStuff] 目标 {target_id} 不在线，缓存机器人投票")
    
    await handle_vote(session_id, vote_message)
