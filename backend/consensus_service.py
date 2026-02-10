from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime

from consensus_engine import (
    get_quorum_threshold,
    get_local_quorum_threshold,
    get_next_phase,
    check_safe_node,
    update_node_locked_qc,
    update_node_prepare_qc,
)
from topology_manager import get_current_leader, get_topology_info


class ConsensusService:
    """
    负责纯粹的共识状态机逻辑：
    - 消息校验（视图、角色、目标等）
    - 阈值统计和 QC 生成
    - SafeNode 检查
    - lockedQC / prepareQC 更新
    - 共识结果与复杂度统计计算

    约束：
    - 不依赖 Socket.IO （无 sio、无 emit）
    - 不做任何网络发送或持久化，只读写传入的 session 状态
    """

    # ==================== Proposal 处理 ====================

    def handle_proposal(
        self,
        session: Dict[str, Any],
        proposal_msg: Dict[str, Any],
        node_id: int,
    ) -> Dict[str, Any]:
        """
        处理 Replica 节点收到的 Proposal 消息（HotStuff PRE-PREPARE）

        返回：
            {
                "accepted": bool,          # 是否通过 SafeNode 检查
                "buffered": bool,          # 是否被缓冲
                "reason": str,             # 日志原因
            }
        """
        proposal_view = proposal_msg.get("view", -1)
        proposal_value = proposal_msg.get("value")
        proposal_qc = proposal_msg.get("qc")
        proposer_id = proposal_msg.get("from")
        current_view = session["current_view"]

        # Proposal 的 view 大于当前 view，需要缓冲
        if proposal_view > current_view:
            buffer = session.setdefault("message_buffer", {})
            node_buffer = buffer.setdefault(node_id, {})
            node_buffer.setdefault(proposal_view, []).append(
                {"type": "proposal", "msg": proposal_msg}
            )
            return {
                "accepted": False,
                "buffered": True,
                "reason": f"proposal_view {proposal_view} > current_view {current_view}, buffered",
            }

        # Proposal 的 view 小于当前 view，忽略
        if proposal_view < current_view:
            return {
                "accepted": False,
                "buffered": False,
                "reason": f"old proposal view {proposal_view} < current_view {current_view}, ignored",
            }

        # 验证消息来自当前视图的 Leader（HotStuff 星型拓扑要求）
        leader_id = get_current_leader(session, proposal_view)
        if proposer_id != leader_id:
            return {
                "accepted": False,
                "buffered": False,
                "reason": f"proposal from non-leader {proposer_id}, leader is {leader_id}",
            }

        # HotStuff SafeNode 谓词检查（Safety 的核心机制）
        if not check_safe_node(session, node_id, proposal_view, proposal_value, proposal_qc):
            return {
                "accepted": False,
                "buffered": False,
                "reason": f"SafeNode failed for node {node_id} at view {proposal_view}",
            }

        return {
            "accepted": True,
            "buffered": False,
            "reason": f"SafeNode passed for node {node_id} at view {proposal_view}",
        }

    # ==================== QC 处理 ====================

    def handle_qc_for_node(
        self,
        session: Dict[str, Any],
        qc_msg: Dict[str, Any],
        node_id: int,
    ) -> None:
        """
        收到 QC 后更新节点的 prepareQC / lockedQC。
        """
        qc = qc_msg.get("qc", {})
        qc_phase = qc.get("phase", "")

        # 更新 prepareQC / highQC（用于 New-View）
        update_node_prepare_qc(session, node_id, qc)

        # Commit 阶段 QC 更新 lockedQC
        if qc_phase == "commit":
            update_node_locked_qc(session, node_id, qc)

    def handle_qc_for_all_nodes(
        self,
        session: Dict[str, Any],
        qc_msg: Dict[str, Any],
    ) -> None:
        """
        对所有节点应用 QC 更新（prepareQC / lockedQC）。
        """
        n = session["config"]["nodeCount"]
        for node_id in range(n):
            self.handle_qc_for_node(session, qc_msg, node_id)

    # ==================== 投票与 QC 聚合 ====================

    def _process_member_vote(
        self,
        session: Dict[str, Any],
        voter_info: Dict[str, Any],
        vote_message: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        处理 Member -> Group Leader 的投票，负责：
        - 校验投票目标
        - 组内阈值统计
        - 在达到阈值时生成 GroupVote（但不发送）

        返回：
            {
                "status": "pending" | "group_vote_generated" | "invalid_target",
                "group_vote": Optional[Dict[str, Any]]
            }
        """
        view = vote_message.get("view", session.get("current_view", 0))
        phase = vote_message.get("phase", "prepare")
        value = vote_message.get("value")
        voter = vote_message.get("from")
        target_id = vote_message.get("to")

        group_leader_id = voter_info["parent_id"]
        if target_id != group_leader_id:
            return {
                "status": "invalid_target",
                "group_vote": None,
            }

        # 存储到组内投票池
        key = (view, phase, value, group_leader_id)
        pending_group_votes = session.setdefault("pending_group_votes", {})
        group_voters = pending_group_votes.setdefault(key, set())
        group_voters.add(voter)

        group_size = voter_info["group_size"]
        local_threshold = get_local_quorum_threshold(session, group_size)

        if len(group_voters) < local_threshold:
            return {
                "status": "pending",
                "group_vote": None,
            }

        # 组内达到阈值，生成 GroupVote（但不负责实际发送）
        global_leader_id = get_current_leader(session, view)
        current_round = session.get("current_round", 1)
        group_vote_message = {
            "from": group_leader_id,
            "to": global_leader_id,
            "type": "vote",
            "value": value,
            "phase": phase,
            "view": view,
            "round": current_round,
            "is_group_vote": True,
            "weight": len(group_voters),
            "group_id": voter_info["group_id"],
            "group_voters": list(group_voters),
            "timestamp": datetime.now().isoformat(),
        }

        # 写入会话消息历史（纯状态更新）
        session["messages"]["vote"].append(group_vote_message)

        return {
            "status": "group_vote_generated",
            "group_vote": group_vote_message,
        }

    def _process_global_vote(
        self,
        session: Dict[str, Any],
        vote_message: Dict[str, Any],
        voter_role: str,
        voter_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        处理 Group Leader / Global Leader -> Global Leader 的投票聚合，负责：
        - 校验目标是否为 Global Leader
        - 权重累加
        - 检查是否达到全局阈值并生成 QC（但不发送）

        返回：
            {
                "status": "pending" | "invalid_target" | "qc_generated",
                "qc_message": Optional[Dict[str, Any]],
                "next_phase": Optional[str],
                "total_weight": int,
                "threshold": int,
                "routing": Optional[Dict[str, Any]]  # QC 分层广播的目标信息（节点 id）
            }
        """
        view = vote_message.get("view", session.get("current_view", 0))
        phase = vote_message.get("phase", "prepare")
        value = vote_message.get("value")
        voter = vote_message.get("from")
        target_id = vote_message.get("to")
        is_group_vote = vote_message.get("is_group_vote", False)
        vote_weight = vote_message.get("weight", 1)

        global_leader_id = get_current_leader(session, view)

        # 验证投票目标
        if voter_role == "group_leader":
            if target_id != global_leader_id:
                return {
                    "status": "invalid_target",
                    "qc_message": None,
                    "next_phase": None,
                    "total_weight": 0,
                    "threshold": 0,
                    "routing": None,
                }
        elif voter_role == "root":
            if target_id != global_leader_id:
                return {
                    "status": "invalid_target",
                    "qc_message": None,
                    "next_phase": None,
                    "total_weight": 0,
                    "threshold": 0,
                    "routing": None,
                }
        else:
            # 非法角色
            return {
                "status": "invalid_target",
                "qc_message": None,
                "next_phase": None,
                "total_weight": 0,
                "threshold": 0,
                "routing": None,
            }

        # Global Leader 收集投票（包括 GroupVote 和直接投票）
        key = (view, phase, value)
        pending = session.setdefault("pending_votes", {})

        if key not in pending:
            pending[key] = {"total_weight": 0, "group_votes": []}

        if is_group_vote:
            pending[key]["total_weight"] += vote_weight
            pending[key]["group_votes"].append(
                {
                    "from": voter,
                    "weight": vote_weight,
                    "group_voters": vote_message.get("group_voters", []),
                }
            )
        else:
            pending[key]["total_weight"] += 1
            pending[key]["group_votes"].append(
                {
                    "from": voter,
                    "weight": 1,
                    "group_voters": [voter],
                }
            )

        threshold = get_quorum_threshold(session)
        total_weight = pending[key]["total_weight"]

        if total_weight < threshold:
            return {
                "status": "pending",
                "qc_message": None,
                "next_phase": None,
                "total_weight": total_weight,
                "threshold": threshold,
                "routing": None,
            }

        # 达到阈值，生成 QC
        all_voters = set()
        for gv in pending[key]["group_votes"]:
            all_voters.update(gv.get("group_voters", [gv["from"]]))

        qc = {
            "phase": phase,
            "view": view,
            "signers": list(all_voters),
            "value": value,
            "total_weight": total_weight,
            "is_multi_layer": True,
        }

        next_phase = get_next_phase(phase)
        session["phase"] = next_phase
        session["phase_step"] = session.get("phase_step", 0) + 1

        current_round = session.get("current_round", 1)
        qc_message = {
            "from": global_leader_id,
            "to": "group_leaders",
            "type": "qc",
            "phase": phase,
            "next_phase": next_phase,
            "view": view,
            "round": current_round,
            "qc": qc,
            "timestamp": datetime.now().isoformat(),
        }

        # 写入会话历史（纯状态更新）
        session["messages"]["qc"].append(qc_message)

        # 计算分层广播的目标（纯 ID 计算，不涉及网络）
        n = session["config"]["nodeCount"]
        branch_count = session["config"].get("branchCount", 2)
        group_size = max(1, n // branch_count)

        group_leaders: List[int] = []
        for gid in range(branch_count):
            group_start_id = gid * group_size
            if group_start_id < n and group_start_id != global_leader_id:
                group_leaders.append(group_start_id)

        members_by_group_leader: Dict[int, List[int]] = {}
        for gl_id in group_leaders:
            gl_info = get_topology_info(session, gl_id, view)
            group_id = gl_info["group_id"]
            group_start_id = group_id * group_size
            group_end_id = min((group_id + 1) * group_size, n)
            members_by_group_leader[gl_id] = list(range(group_start_id + 1, group_end_id))

        routing = {
            "global_leader": global_leader_id,
            "group_leaders": group_leaders,
            "members_by_group_leader": members_by_group_leader,
        }

        return {
            "status": "qc_generated",
            "qc_message": qc_message,
            "next_phase": next_phase,
            "total_weight": total_weight,
            "threshold": threshold,
            "routing": routing,
        }

    def handle_vote(
        self,
        session: Dict[str, Any],
        vote_message: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        双层 HotStuff 投票处理（纯逻辑版本）。

        不做任何网络发送，只更新 session 并返回需要网络层执行的动作：

        返回结构（根据场景部分字段可能缺失）：
            {
                "status": "buffered" | "ignored" | "pending" | "group_vote_generated" | "qc_generated",
                "group_vote": Optional[Dict[str, Any]],
                "qc_message": Optional[Dict[str, Any]],
                "routing": Optional[Dict[str, Any]],   # QC 分层广播目标
            }
        """
        view = vote_message.get("view", session.get("current_view", 0))
        phase = vote_message.get("phase", "prepare")
        voter = vote_message.get("from")
        value = vote_message.get("value")
        current_view = session["current_view"]

        # 视图检查：大于当前视图 -> 缓冲
        if view > current_view:
            buffer = session.setdefault("message_buffer", {})
            buffer.setdefault(view, []).append(vote_message)
            return {"status": "buffered"}

        # 小于当前视图 -> 忽略
        if view < current_view:
            return {"status": "ignored"}

        voter_info = get_topology_info(session, voter, view)
        voter_role = voter_info["role"]

        # ========== Case A: Member -> Group Leader ==========
        if voter_role == "member":
            result = self._process_member_vote(session, voter_info, vote_message)
            if result["status"] != "group_vote_generated":
                # 尚未到阈值或目标非法
                return {
                    "status": result["status"],
                    "group_vote": result.get("group_vote"),
                }

            # 组内达到阈值，已经在 _process_member_vote 中生成了 GroupVote 并写入 session["messages"]["vote"]
            group_vote = result["group_vote"]

            # 同时在全局层面继续按投票处理（但这里仍然不做网络发送）
            global_result = self._process_global_vote(
                session,
                group_vote,
                voter_role="group_leader",
                voter_info=voter_info,
            )

            status = (
                "qc_generated"
                if global_result["status"] == "qc_generated"
                else "group_vote_generated"
            )

            return {
                "status": status,
                "group_vote": group_vote,
                "qc_message": global_result.get("qc_message"),
                "routing": global_result.get("routing"),
            }

        # ========== Case B: Group Leader / Global Leader -> Global Leader ==========
        if voter_role in ("group_leader", "root"):
            global_result = self._process_global_vote(
                session,
                vote_message,
                voter_role=voter_role,
                voter_info=voter_info,
            )
            return {
                "status": global_result["status"],
                "qc_message": global_result.get("qc_message"),
                "routing": global_result.get("routing"),
            }

        # 其他未知角色
        return {"status": "ignored"}

    # ==================== 共识完成统计（Shadow Calculation） ====================

    def finalize_consensus_state(
        self,
        session: Dict[str, Any],
        status: str = "Consensus Completed",
        description: str = "Consensus completed",
    ) -> Dict[str, Any]:
        """
        完成共识时，计算并更新会话内的共识结果和复杂度对比数据。

        仅修改 session 内存，不做任何网络或数据库操作。

        返回：
            {
                "consensus_result": Dict[str, Any],
                "history_item": Dict[str, Any],
            }
        """
        current_view = session["current_view"]
        if session.get("consensus_finalized_view") == current_view:
            # 已经计算过，直接返回现有结果
            return {
                "consensus_result": session.get("consensus_result"),
                "history_item": session["consensus_history"][-1]
                if session.get("consensus_history")
                else None,
            }

        session["consensus_finalized_view"] = current_view

        session["phase"] = "completed"
        session["phase_step"] = 4
        session["status"] = "completed"

        config = session["config"]

        # ================= 通信复杂度统计报告（4种算法对比） =================
        network_stats = session.get("network_stats", {})
        actual_messages = network_stats.get("total_messages_sent", 0)
        n = config["nodeCount"]
        branch_count = config.get("branchCount", 2)

        k = max(1, branch_count)
        group_size = n // k if k > 0 else n

        # Shadow 计算（本实现保持原有公式）
        shadow_pbft_actual = 2 * n * (n - 1)
        shadow_hotstuff_actual = 8 * (n - 1)
        shadow_multilayer_actual = (2 * k * (k - 1)) + (k * 2 * group_size * (group_size - 1))

        theoretical_double_hotstuff = 8 * n
        theoretical_pbft = 2 * n * n
        theoretical_hotstuff = 4 * n
        theoretical_multilayer = 2 * k * k + 2 * n * n // k

        hotstuff_double_actual = actual_messages

        optimization_vs_pbft_pure = (
            theoretical_pbft / hotstuff_double_actual if hotstuff_double_actual > 0 else 0.0
        )
        optimization_vs_hotstuff_pure = (
            theoretical_hotstuff / hotstuff_double_actual if hotstuff_double_actual > 0 else 0.0
        )
        optimization_vs_pbft_multi = (
            theoretical_multilayer / hotstuff_double_actual if hotstuff_double_actual > 0 else 0.0
        )

        complexity_comparison = {
            "double_hotstuff": {
                "name": "Double-Layer HotStuff (System)",
                "theoretical": theoretical_double_hotstuff,
                "actual": hotstuff_double_actual,
                "complexity": "O(N)",
                "is_current": True,
            },
            "pbft_pure": {
                "name": "PBFT (Pure)",
                "theoretical": theoretical_pbft,
                "actual": shadow_pbft_actual,
                "complexity": "O(N²)",
                "optimization_ratio": optimization_vs_pbft_pure,
            },
            "hotstuff_pure": {
                "name": "HotStuff (Pure)",
                "theoretical": theoretical_hotstuff,
                "actual": shadow_hotstuff_actual,
                "complexity": "O(N)",
                "optimization_ratio": optimization_vs_hotstuff_pure,
            },
            "pbft_multi_layer": {
                "name": "PBFT (Multi-Layer)",
                "theoretical": theoretical_multilayer,
                "actual": shadow_multilayer_actual,
                "complexity": "O(K² + N²/K)",
                "optimization_ratio": optimization_vs_pbft_multi,
            },
        }

        consensus_result = {
            "status": status,
            "description": description,
            "stats": {
                "expected_nodes": config["nodeCount"],
                "expected_prepare_nodes": config["nodeCount"] - 1,
                "total_messages": len(session["messages"].get("prepare", []))
                + len(session["messages"].get("commit", [])),
                "complexity_comparison": complexity_comparison,
                "network_stats": {
                    "actual_messages": actual_messages,
                    "node_count": n,
                    "branch_count": branch_count,
                },
            },
        }

        session["consensus_result"] = consensus_result

        current_round = session.get("current_round", 1)
        history_item = {
            "round": current_round,
            "view": session["current_view"],
            "status": status,
            "description": description,
            "stats": consensus_result.get("stats"),
            "timestamp": datetime.now().isoformat(),
        }
        session.setdefault("consensus_history", []).append(history_item)

        return {
            "consensus_result": consensus_result,
            "history_item": history_item,
        }

