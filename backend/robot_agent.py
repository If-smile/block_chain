from typing import Dict, Any, List, Optional
from datetime import datetime

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

