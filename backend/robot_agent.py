"""
机器人/代理行为模块：自动化投票、提案发送、任务调度。

- RobotAgent：纯逻辑（生成提案/投票、状态重置），不依赖 Socket.IO。
- 本模块还提供与网络层协作的异步函数（发送、调度），通过回调依赖 socket_handlers 的 handle_vote、finalize_consensus 等，避免循环导入。
"""

from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime
import asyncio

from state import (
    sio,
    get_session,
    node_sockets,
    connected_nodes,
    should_deliver_message,
    count_message_sent,
)
from topology_manager import get_current_leader, get_topology_info


class RobotAgent:
    """
    机器人节点行为代理（纯逻辑层，不做网络发送）：
    - 根据当前视图 / 阶段，为机器人生成提案和投票消息
    - 维护和更新 robot_node_states 结构（存放在 session 中）

    约束：
    - 不依赖 Socket.IO（无 sio、无 emit）
    - 不直接调用数据库或其他 I/O
    """

    # ==================== 机器人状态管理 ====================

    def reset_states_for_view_change(self, session: Dict[str, Any]) -> None:
        """
        在视图切换时重置机器人节点的投票状态（但保持身份）。
        """
        for robot_id in session.get("robot_nodes", []):
            session.setdefault("robot_node_states", {})
            session["robot_node_states"][robot_id] = {
                "received_pre_prepare": False,
                "received_prepare_count": 0,
                "received_commit_count": 0,
                "sent_prepare": False,
                "sent_commit": False,
            }

    def reset_states_for_new_round(self, session: Dict[str, Any]) -> None:
        """
        在新一轮开始时重置机器人节点的投票状态。
        """
        for robot_id in session.get("robot_nodes", []):
            session.setdefault("robot_node_states", {})
            session["robot_node_states"][robot_id] = {
                "received_pre_prepare": False,
                "received_prepare_count": 0,
                "received_commit_count": 0,
                "sent_prepare": False,
                "sent_commit": False,
            }

    def mark_proposal_received_by_robots(self, session: Dict[str, Any], proposer_id: int) -> None:
        """
        标记所有（非 Leader）机器人节点已经收到 Proposal。
        """
        for robot_id in session.get("robot_nodes", []):
            if robot_id == proposer_id:
                continue
            session.setdefault("robot_node_states", {})
            state = session["robot_node_states"].setdefault(robot_id, {})
            state["received_pre_prepare"] = True

    # ==================== 提案生成 ====================

    def generate_proposal(
        self,
        session: Dict[str, Any],
        high_qc: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        为当前视图的 Leader 生成 Proposal（PRE-PREPARE）消息（不发送）。

        返回：
            Proposal 消息字典，或 None（如果 Leader 不是机器人）
        """
        current_view = session["current_view"]
        last_view = session.get("last_pre_prepare_view")
        if last_view == current_view:
            # 已经为该视图生成过 Proposal
            return None

        proposer_id = get_current_leader(session)
        if proposer_id not in session.get("robot_nodes", []):
            # Leader 是人类节点，由前端控制
            return None

        session["last_pre_prepare_view"] = current_view

        config = session["config"]
        proposal_value = config["proposalValue"]
        if high_qc:
            proposal_value = high_qc.get("value", proposal_value)

        current_round = session.get("current_round", 1)
        message = {
            "from": proposer_id,
            "to": "group_leaders",
            "type": "pre_prepare",
            "value": proposal_value,
            "phase": "prepare",
            "view": current_view,
            "round": current_round,
            "qc": high_qc,
            "timestamp": datetime.now().isoformat(),
            "tampered": False,
            "isRobot": True,
        }

        # 写入会话历史（纯状态）
        session["messages"]["pre_prepare"].append(message)

        return message

    # ==================== 投票生成 ====================

    def generate_vote_for_robot(
        self,
        session: Dict[str, Any],
        robot_id: int,
        phase: str,
        value: int,
    ) -> Optional[Dict[str, Any]]:
        """
        生成单个机器人节点在指定阶段（prepare/commit）的投票消息（不发送）。
        """
        current_view = session["current_view"]
        node_info = get_topology_info(session, robot_id, current_view)
        target_id = node_info["parent_id"]

        # Root (Global Leader) 不需要给自己投票
        if node_info["role"] == "root":
            return None

        current_round = session.get("current_round", 1)
        vote_message = {
            "from": robot_id,
            "to": target_id,
            "type": "vote",
            "value": value,
            "phase": phase,
            "view": current_view,
            "round": current_round,
            "qc": None,
            "timestamp": datetime.now().isoformat(),
            "tampered": False,
            "isRobot": True,
        }

        # 写入会话历史（纯状态）
        session["messages"]["vote"].append(vote_message)

        return vote_message

    def generate_votes_for_phase(
        self,
        session: Dict[str, Any],
        view: int,
        phase: str,
        value: int,
    ) -> List[Dict[str, Any]]:
        """
        为当前视图指定阶段生成所有机器人节点的投票消息（不发送）。

        注意：状态检查（视图是否已切换等）应由调用方在网络层处理。
        """
        votes: List[Dict[str, Any]] = []
        leader_id = get_current_leader(session)

        for robot_id in session.get("robot_nodes", []):
            if robot_id == leader_id:
                # Global Leader 一般不再给自己单独发 vote 消息
                continue

            node_info = get_topology_info(session, robot_id, view)
            if node_info["role"] == "root":
                continue

            vote = self.generate_vote_for_robot(session, robot_id, phase, value)
            if vote is not None:
                votes.append(vote)

        return votes


# 本模块内使用的 RobotAgent 实例（类定义完成后创建）
robot_agent = RobotAgent()


# ==================== 机器人节点创建与启动 ====================

async def create_robot_nodes_and_start(
    session_id: str,
    robot_count: int,
    *,
    start_pbft_process_cb: Callable[[str], Awaitable[None]],
) -> None:
    """创建机器人节点并立即启动 HotStuff 流程。start_pbft_process_cb 由 socket_handlers 注入。"""
    session = get_session(session_id)
    if not session:
        return
    # 仿真模式下大幅缩短等待时间以提升吞吐
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 1.0
    await asyncio.sleep(delay)
    print(f"创建{robot_count}个机器人节点")
    for robot_id in range(robot_count):
        session["robot_nodes"].append(robot_id)
        connected_nodes[session_id].append(robot_id)
        print(f"机器人节点 {robot_id} 已创建")
        session["robot_node_states"][robot_id] = {
            "received_pre_prepare": False,
            "received_prepare_count": 0,
            "received_commit_count": 0,
            "sent_prepare": False,
            "sent_commit": False,
        }
    print(f"机器人节点准备完毕，立即开始PBFT共识流程")
    await start_pbft_process_cb(session_id)


# ==================== 机器人投票触发与发送 ====================

async def trigger_robot_votes(
    session_id: str,
    view: int,
    phase: str,
    value: int,
    *,
    handle_vote_cb: Callable[[str, Dict[str, Any]], Awaitable[None]],
    finalize_consensus_cb: Callable[[str, str, str], Awaitable[None]],
) -> None:
    """进入新阶段时触发机器人节点发送投票。handle_vote、finalize_consensus 由 socket_handlers 注入。"""
    print(f"触发机器人自动投票: session={session_id}, view={view}, phase={phase}")
    session = get_session(session_id)
    if not session:
        return
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 2.0
    await asyncio.sleep(delay)
    if session.get("current_view") != view:
        print(f"视图已从 {view} 切换为 {session.get('current_view')}，取消本次自动投票")
        return
    if phase == "decide":
        print(f"进入 Decide 阶段，直接完成共识: view={view}")
        await finalize_consensus_cb(session_id, "Consensus Success", f"View {view} consensus reached")
        return
    votes = robot_agent.generate_votes_for_phase(session, view, phase, value)
    for vote_msg in votes:
        # 1. 模拟 Leader 广播 QC 到 Replica 的前向丢包 (Forward Drop)
        if not should_deliver_message(session_id):
            continue
            
        target_id = vote_msg["to"]
        node_info = get_topology_info(session, vote_msg["from"], view)
        target_sid = node_sockets.get(session_id, {}).get(target_id)
        count_message_sent(session_id, is_broadcast=False)
        
        # 2. 模拟 Replica 发回 Vote 的反向丢包 (Reverse Drop)
        delivered = should_deliver_message(session_id)
        
        if target_sid and delivered:
            await sio.emit("message_received", vote_msg, room=target_sid)
            role_name = "Group Leader" if node_info["role"] == "member" else "Global Leader"
            print(f"[双层 HotStuff] 机器人节点 {vote_msg['from']} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE({phase})")
            
        if delivered:
            await handle_vote_cb(session_id, vote_msg)


async def robot_send_pre_prepare(
    session_id: str,
    highQC: Optional[Dict] = None,
    *,
    handle_consensus_timeout_cb: Callable[[str, int], Awaitable[None]],
    handle_proposal_message_cb: Optional[Callable[[str, Dict[str, Any], int], Awaitable[bool]]] = None,
    handle_robot_prepare_cb: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> None:
    """Leader 发送 Proposal（HotStuff PRE-PREPARE）。超时与 prepare 回调由调用方注入。"""
    session = get_session(session_id)
    if not session:
        return
    message = robot_agent.generate_proposal(session, highQC)
    if message is None:
        current_view = session.get("current_view", 0)
        proposer_id = get_current_leader(session)
        print(f"Leader {proposer_id} 在 View {current_view} 不是机器人节点，等待人类操作")
        return
    current_view = message["view"]
    proposer_id = message["from"]
    config = session["config"]
    n = config["nodeCount"]

    # 根据通用拓扑引擎确定所有组长（不包括 Global Leader 自己）
    group_leaders: List[int] = []
    proposer_group_members: List[int] = []
    for node_id in range(n):
        info = get_topology_info(session, node_id, current_view)
        if info["role"] == "group_leader" and node_id != proposer_id:
            group_leaders.append(node_id)
        # Proposer 自己组内的成员（parent_id == proposer_id 且角色为 member），必须直接收到 Proposal
        if info["role"] == "member" and info.get("parent_id") == proposer_id:
            proposer_group_members.append(node_id)
    if group_leaders:
        count_message_sent(session_id, is_broadcast=False, target_count=len(group_leaders))
    for gl_id in group_leaders:
        gl_sid = node_sockets.get(session_id, {}).get(gl_id)
        if gl_sid:
            if should_deliver_message(session_id):
                await sio.emit("message_received", message, room=gl_sid)
            else:
                print(f"[网络模拟] Proposal 消息被丢弃 (目标: Group Leader {gl_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    for gl_id in group_leaders:
        forward_message = message.copy()
        forward_message["from"] = gl_id
        forward_message["to"] = "group_members"

        # 通过拓扑信息查找该组长负责的所有成员（parent_id == gl_id）
        members: List[int] = []
        for node_id in range(n):
            info = get_topology_info(session, node_id, current_view)
            if info.get("parent_id") == gl_id and info["role"] == "member":
                members.append(node_id)

        target_member_count = len(members)
        if target_member_count > 0:
            count_message_sent(session_id, is_broadcast=False, target_count=target_member_count)

        for member_id in members:
            member_sid = node_sockets.get(session_id, {}).get(member_id)
            if member_sid:
                if should_deliver_message(session_id):
                    await sio.emit("message_received", forward_message, room=member_sid)
                    print(f"[路由] Node {gl_id} -> Node {member_id} (Role: member)")
                else:
                    print(f"[网络模拟] Proposal 转发消息被丢弃 (目标: Member {member_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)")
    # Proposer 向自己所在小组成员直接广播 Proposal，避免提案孤岛
    if proposer_group_members:
        count_message_sent(session_id, is_broadcast=False, target_count=len(proposer_group_members))
        for member_id in proposer_group_members:
            member_sid = node_sockets.get(session_id, {}).get(member_id)
            if member_sid:
                if should_deliver_message(session_id):
                    await sio.emit("message_received", message, room=member_sid)
                    print(f"[路由] Node {proposer_id} -> Node {member_id} (Role: member, same group as root)")
                else:
                    print(
                        f"[网络模拟] Proposal 转发消息被丢弃 (目标: Member {member_id}, 传递率: "
                        f"{session['config'].get('messageDeliveryRate', 100)}%)"
                    )

    # 仍然向会话房间广播，用于前端动画展示
    await sio.emit("message_received", message, room=session_id)
    print(
        f"[双层 HotStuff] Global Leader {proposer_id} (View {current_view}) 发送了 Proposal 消息: "
        f"value={message['value']}, highQC.view={message['qc'].get('view') if message.get('qc') else None}"
    )
    print(f"[双层 HotStuff] Proposal 通过分层广播：Global Leader -> {len(group_leaders)} Group Leaders -> Members")
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 1.0
    await asyncio.sleep(delay)
    session["phase"] = "prepare"
    session["phase_step"] = 1
    await sio.emit(
        "phase_update",
        {"phase": "prepare", "step": 1, "leader": proposer_id, "view": current_view},
        room=session_id,
    )
    print(f"会话 {session_id} View {current_view} 进入准备阶段")
    timeout_task = asyncio.create_task(handle_consensus_timeout_cb(session_id, current_view))
    session["timeout_task"] = timeout_task
    print(f"View {current_view} 共识超时检查已启动（40秒后触发 View Change）")
    robot_agent.mark_proposal_received_by_robots(session, proposer_id)
    if handle_proposal_message_cb is not None and handle_robot_prepare_cb is not None:
        asyncio.create_task(
            robot_send_prepare_messages(
                session_id,
                handle_proposal_message_cb=handle_proposal_message_cb,
                handle_robot_prepare_cb=handle_robot_prepare_cb,
            )
        )


async def robot_send_prepare_messages(
    session_id: str,
    *,
    handle_proposal_message_cb: Optional[Callable[[str, Dict[str, Any], int], Awaitable[bool]]] = None,
    handle_robot_prepare_cb: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> None:
    """机器人节点自动发送 Prepare 阶段 VOTE。依赖 handle_proposal_message、handle_robot_prepare 由调用方注入。"""
    if not handle_proposal_message_cb or not handle_robot_prepare_cb:
        raise ValueError("robot_send_prepare_messages 需要 handle_proposal_message_cb 与 handle_robot_prepare_cb")
    session = get_session(session_id)
    if not session:
        return
    current_view = session["current_view"]
    proposal_msgs = [m for m in session["messages"]["pre_prepare"] if m.get("view") == current_view]
    if not proposal_msgs:
        print(f"View {current_view}: 未找到 Proposal 消息，机器人节点不投票")
        return
    proposal_msg = proposal_msgs[-1]
    print(f"View {current_view}: 机器人节点将在10秒后发送 VOTE(prepare) 给 Leader")
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 10.0
    await asyncio.sleep(delay)
    session = get_session(session_id)
    if not session:
        return
    if session["current_view"] != current_view:
        print(f"视图已改变（{current_view} -> {session['current_view']}），放弃发送投票")
        return
    leader_id = get_current_leader(session, current_view)
    for robot_id in session.get("robot_nodes", []):
        if robot_id == leader_id:
            continue
        if session["robot_node_states"][robot_id].get("sent_prepare"):
            continue
        if not should_deliver_message(session_id):
            print(f"[网络模拟] 节点 {robot_id} 未收到 Proposal(丢包)，不发选票")
            continue
        await handle_proposal_message_cb(session_id, proposal_msg, robot_id)
        session["robot_node_states"][robot_id]["sent_prepare"] = True


async def handle_robot_prepare(
    session_id: str,
    robot_id: int,
    value: int,
    *,
    handle_vote_cb: Callable[[str, Dict[str, Any]], Awaitable[None]],
) -> None:
    """处理机器人 Prepare 阶段投票（双层 HotStuff）。handle_vote 由调用方注入。"""
    session = get_session(session_id)
    if not session:
        return
    vote_message = robot_agent.generate_vote_for_robot(session, robot_id, "prepare", value)
    if vote_message is None:
        print(f"[双层 HotStuff] Global Leader {robot_id} 不需要给自己投票")
        return
    target_id = vote_message["to"]
    node_info = get_topology_info(session, robot_id, session["current_view"])
    target_sid = node_sockets.get(session_id, {}).get(target_id)
    count_message_sent(session_id, is_broadcast=False)
    delivered = should_deliver_message(session_id)
    if delivered:
        if target_sid:
            await sio.emit("message_received", vote_message, room=target_sid)
            role_name = "Group Leader" if node_info["role"] == "member" else "Global Leader"
            print(f"[双层 HotStuff] 机器人节点 {robot_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE(prepare) [View {session['current_view']}]")
        else:
            print(f"[双层 HotStuff] 目标 {target_id} 不在线，缓存机器人投票")
        await handle_vote_cb(session_id, vote_message)
    else:
        print(
            f"[网络模拟] 后端拦截: 机器人 VOTE(prepare) 丢包 "
            f"(from={robot_id}, to={target_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)"
        )


async def schedule_robot_prepare(
    session_id: str,
    robot_id: int,
    value: int,
    *,
    handle_robot_prepare_cb: Callable[[str, int, int], Awaitable[None]],
) -> None:
    """调度机器人节点在短暂延迟后发送准备阶段投票。"""
    session = get_session(session_id)
    if not session:
        return
    current_view = session["current_view"]
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 2.0
    await asyncio.sleep(delay)
    session = get_session(session_id)
    if not session:
        return
    if session["current_view"] != current_view:
        print(f"视图已改变（{current_view} -> {session['current_view']}），节点{robot_id}放弃发送准备消息")
        return
    if session.get("phase") != "prepare":
        print(f"阶段已改变，节点{robot_id}放弃发送准备消息")
        return
    await handle_robot_prepare_cb(session_id, robot_id, value)


async def check_robot_nodes_ready_for_commit(session_id: str) -> None:
    """HotStuff 中提交阶段由 Leader 收齐 QC 后推进，此处仅保留占位。"""
    return


async def schedule_robot_commit(
    session_id: str,
    robot_id: int,
    value: int,
    *,
    handle_robot_commit_cb: Callable[[str, int, int], Awaitable[None]],
) -> None:
    """调度机器人节点在延迟后发送提交消息。"""
    session = get_session(session_id)
    if not session:
        return
    current_round = session["current_round"]
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 10.0
    await asyncio.sleep(delay)
    session = get_session(session_id)
    if not session:
        return
    if session["current_round"] != current_round:
        print(f"轮次已改变（{current_round} -> {session['current_round']}），节点{robot_id}放弃发送提交消息")
        return
    await handle_robot_commit_cb(session_id, robot_id, value)


async def handle_robot_commit(
    session_id: str,
    robot_id: int,
    value: int,
    *,
    handle_vote_cb: Callable[[str, Dict[str, Any]], Awaitable[None]],
) -> None:
    """处理机器人提交阶段投票（双层 HotStuff）。handle_vote 由调用方注入。"""
    session = get_session(session_id)
    if not session:
        return
    vote_message = robot_agent.generate_vote_for_robot(session, robot_id, "commit", value)
    if vote_message is None:
        print(f"[双层 HotStuff] Global Leader {robot_id} 不需要给自己投票")
        return
    target_id = vote_message["to"]
    node_info = get_topology_info(session, robot_id, session["current_view"])
    target_sid = node_sockets.get(session_id, {}).get(target_id)
    count_message_sent(session_id, is_broadcast=False)
    delivered = should_deliver_message(session_id)
    if delivered:
        if target_sid:
            await sio.emit("message_received", vote_message, room=target_sid)
            role_name = "Group Leader" if node_info["role"] == "member" else "Global Leader"
            print(f"[双层 HotStuff] 机器人节点 {robot_id} ({node_info['role']}) 向 {role_name} {target_id} 发送 VOTE(commit)")
        else:
            print(f"[双层 HotStuff] 目标 {target_id} 不在线，缓存机器人投票")
        await handle_vote_cb(session_id, vote_message)
    else:
        print(
            f"[网络模拟] 后端拦截: 机器人 VOTE(commit) 丢包 "
            f"(from={robot_id}, to={target_id}, 传递率: {session['config'].get('messageDeliveryRate', 100)}%)"
        )

