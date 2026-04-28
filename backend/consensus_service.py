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
    Pure consensus state-machine logic.

    Responsibilities:
    - Message validation (view, role, destination)
    - Vote aggregation and QC generation
    - SafeNode predicate evaluation
    - lockedQC / prepareQC updates
    - Consensus result and complexity statistics

    Constraints:
    - No Socket.IO dependency (no sio, no emit calls)
    - No network I/O or persistence; only reads/writes the session dict
    """

    # ==================== Proposal handling ====================

    def handle_proposal(
        self,
        session: Dict[str, Any],
        proposal_msg: Dict[str, Any],
        node_id: int,
    ) -> Dict[str, Any]:
        """
        Process a Proposal message received by a replica node (HotStuff Prepare phase).

        Returns:
            {
                "accepted": bool,   # True if SafeNode check passed
                "buffered": bool,   # True if message was buffered for a future view
                "reason":   str,    # Human-readable log reason
            }
        """
        proposal_view = proposal_msg.get("view", -1)
        proposal_value = proposal_msg.get("value")
        proposal_qc = proposal_msg.get("qc")
        proposer_id = proposal_msg.get("from")
        current_view = session["current_view"]

        # Future view: buffer the proposal for later processing
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

        # Stale view: discard
        if proposal_view < current_view:
            return {
                "accepted": False,
                "buffered": False,
                "reason": f"old proposal view {proposal_view} < current_view {current_view}, ignored",
            }

        # Verify the proposal comes from the legitimate leader for this view
        leader_id = get_current_leader(session, proposal_view)
        if proposer_id != leader_id:
            return {
                "accepted": False,
                "buffered": False,
                "reason": f"proposal from non-leader {proposer_id}, leader is {leader_id}",
            }

        # HotStuff SafeNode predicate (core Safety mechanism)
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

    # ==================== QC handling ====================

    def handle_qc_for_node(
        self,
        session: Dict[str, Any],
        qc_msg: Dict[str, Any],
        node_id: int,
    ) -> None:
        """Update a single node's prepareQC and (if Commit phase) lockedQC."""
        qc = qc_msg.get("qc", {})
        qc_phase = qc.get("phase", "")

        # Always update prepareQC / highQC (used in New-View message selection)
        update_node_prepare_qc(session, node_id, qc)

        # Commit-phase QC also updates lockedQC
        if qc_phase == "commit":
            update_node_locked_qc(session, node_id, qc)

    def handle_qc_for_all_nodes(
        self,
        session: Dict[str, Any],
        qc_msg: Dict[str, Any],
    ) -> None:
        """Apply QC updates (prepareQC / lockedQC) to every node in the session."""
        n = session["config"]["nodeCount"]
        for node_id in range(n):
            self.handle_qc_for_node(session, qc_msg, node_id)

    # ==================== Vote aggregation & QC generation ====================

    def _process_member_vote(
        self,
        session: Dict[str, Any],
        voter_info: Dict[str, Any],
        vote_message: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a Member -> Group Leader vote.

        Accumulates votes in the local vote pool and, once the local quorum
        threshold is reached, produces a GroupVote (without sending it).

        Returns:
            {
                "status":     "pending" | "group_vote_generated" | "invalid_target",
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

        # Accumulate vote in the local pool
        key = (view, phase, value, group_leader_id)
        pending_group_votes = session.setdefault("pending_group_votes", {})
        group_voters = pending_group_votes.setdefault(key, set())
        group_voters.add(voter)

        group_size = voter_info["group_size"]
        local_threshold = get_local_quorum_threshold(session, group_size)

        if len(group_voters) < local_threshold:
            return {"status": "pending", "group_vote": None}

        # Deduplicate: only generate one GroupVote per (view, phase, group_leader)
        generated_group_votes = session.setdefault("generated_group_votes", set())
        gv_key = (view, phase, group_leader_id)
        if gv_key in generated_group_votes:
            return {"status": "pending", "group_vote": None}
        generated_group_votes.add(gv_key)

        # Local quorum reached for the first time: generate GroupVote
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
            # BFT safety: weight = actual vote count, consistent with the 2f+1 global quorum
            "weight": len(group_voters),
            "group_id": voter_info["group_id"],
            "group_voters": list(group_voters),
            "timestamp": datetime.now().isoformat(),
        }

        # Persist to session message history (pure state update, no I/O)
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
        Process a Group Leader / Root -> Global Leader vote at the global level.

        Accumulates weighted votes and, once the global quorum threshold is
        reached, generates a QC and computes the broadcast routing table
        (without performing any network I/O).

        Returns:
            {
                "status":       "pending" | "invalid_target" | "ignored" | "qc_generated",
                "qc_message":   Optional[Dict[str, Any]],
                "next_phase":   Optional[str],
                "total_weight": int,
                "threshold":    int,
                "routing":      Optional[Dict[str, Any]]  # node IDs for layered broadcast
            }
        """
        view = vote_message.get("view", session.get("current_view", 0))
        phase = vote_message.get("phase", "prepare")
        value = vote_message.get("value")
        voter = vote_message.get("from")
        target_id = vote_message.get("to")
        is_group_vote = vote_message.get("is_group_vote", False)
        vote_weight = vote_message.get("weight", 1)

        # Ignore votes for a phase the session has already advanced past
        if session.get("phase") != phase:
            return {
                "status": "ignored",
                "qc_message": None,
                "next_phase": None,
                "total_weight": 0,
                "threshold": 0,
                "routing": None,
            }

        global_leader_id = get_current_leader(session, view)

        # Validate that the vote is directed at the correct Global Leader
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
            # Unknown role: reject
            return {
                "status": "invalid_target",
                "qc_message": None,
                "next_phase": None,
                "total_weight": 0,
                "threshold": 0,
                "routing": None,
            }

        # Accumulate weighted votes (GroupVotes and direct votes)
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
        group_id = vote_message.get("group_id", voter_info.get("group_id"))
        print(f"[weight] group {group_id} contributed weight {vote_weight}, total {total_weight}/{threshold}")

        if total_weight < threshold:
            return {
                "status": "pending",
                "qc_message": None,
                "next_phase": None,
                "total_weight": total_weight,
                "threshold": threshold,
                "routing": None,
            }

        # Deduplicate: only generate one QC per (view, phase)
        generated_qcs = session.setdefault("generated_qcs", set())
        qc_key = (view, phase)
        if qc_key in generated_qcs:
            return {
                "status": "pending",
                "qc_message": None,
                "next_phase": None,
                "total_weight": total_weight,
                "threshold": threshold,
                "routing": None,
            }
        generated_qcs.add(qc_key)

        # Global quorum reached for the first time: generate QC
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

        # Persist QC to session history (pure state update, no I/O)
        session["messages"]["qc"].append(qc_message)

        # Compute broadcast routing table (ID arithmetic only, no network calls)
        n = session["config"]["nodeCount"]

        # Step 1: collect all group leaders (excluding root)
        group_leaders: List[int] = []
        for node_id in range(n):
            info = get_topology_info(session, node_id, view)
            if info["role"] == "group_leader":
                group_leaders.append(node_id)

        # Step 2: map each group leader to its member nodes
        members_by_group_leader: Dict[int, List[int]] = {}
        for gl_id in group_leaders:
            members_by_group_leader[gl_id] = []
        for node_id in range(n):
            info = get_topology_info(session, node_id, view)
            parent_id = info.get("parent_id")
            if parent_id in members_by_group_leader and info["role"] == "member":
                members_by_group_leader[parent_id].append(node_id)

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
        Entry point for vote processing in the double-layer HotStuff protocol.

        Performs no network I/O; updates session state and returns an action
        descriptor for the network layer to execute.

        Returns:
            {
                "status":      "buffered" | "ignored" | "pending"
                               | "group_vote_generated" | "qc_generated",
                "group_vote":  Optional[Dict[str, Any]],
                "qc_message":  Optional[Dict[str, Any]],
                "routing":     Optional[Dict[str, Any]],  # layered broadcast targets
            }
        """
        view = vote_message.get("view", session.get("current_view", 0))
        phase = vote_message.get("phase", "prepare")
        voter = vote_message.get("from")
        value = vote_message.get("value")
        current_view = session["current_view"]

        # Future view: buffer for later
        if view > current_view:
            buffer = session.setdefault("message_buffer", {})
            buffer.setdefault(view, []).append(vote_message)
            return {"status": "buffered"}

        # Stale view: discard
        if view < current_view:
            return {"status": "ignored"}

        voter_info = get_topology_info(session, voter, view)
        voter_role = voter_info["role"]

        # ========== Case A: Member -> Group Leader ==========
        if voter_role == "member":
            result = self._process_member_vote(session, voter_info, vote_message)
            if result["status"] != "group_vote_generated":
                # Below local threshold or invalid target
                return {
                    "status": result["status"],
                    "group_vote": result.get("group_vote"),
                }

            # Local quorum reached: GroupVote already written to session["messages"]["vote"]
            group_vote = result["group_vote"]

            # Forward the GroupVote to the global aggregation layer
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

        # ========== Case B: Group Leader / Root -> Global Leader ==========
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

        # Unknown role
        return {"status": "ignored"}

    # ==================== Consensus completion statistics (Shadow Calculation) ====================

    def finalize_consensus_state(
        self,
        session: Dict[str, Any],
        status: str = "Consensus Completed",
        description: str = "Consensus completed",
    ) -> Dict[str, Any]:
        """
        Compute and store consensus results and complexity comparison data when a round completes.

        Only mutates the in-memory session dict — no network or database operations.

        Returns:
            {
                "consensus_result": Dict[str, Any],
                "history_item":     Dict[str, Any],
            }
        """
        current_view = session["current_view"]
        if session.get("consensus_finalized_view") == current_view:
            # Already computed for this view — return cached result
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

        # ================= Communication-complexity comparison (4 algorithms) =================
        network_stats = session.get("network_stats", {})
        actual_messages = network_stats.get("total_messages_sent", 0)
        n = config["nodeCount"]
        branch_count = config.get("branchCount", 2)

        k = max(1, branch_count)
        group_size = n // k if k > 0 else n

        # Shadow message counts (theoretical baseline, using original formulae)
        shadow_pbft_actual = 2 * n * (n - 1)
        shadow_hotstuff_actual = 8 * (n - 1)
        shadow_multilayer_actual = (2 * k * (k - 1)) + (k * 2 * group_size * (group_size - 1))

        theoretical_double_hotstuff = 8 * n
        theoretical_pbft = 2 * n * n
        theoretical_hotstuff = 4 * n
        theoretical_multilayer = 2 * k * k + 2 * n * n // k
        # Chained HotStuff: messages per confirmed block in steady state = 2N
        theoretical_chained_hotstuff = 2 * n

        hotstuff_double_actual = actual_messages
        # Guard against division by zero; floor divisor at 1
        divisor = max(1, actual_messages)
        optimization_vs_pbft_pure = theoretical_pbft / divisor
        optimization_vs_hotstuff_pure = theoretical_hotstuff / divisor
        optimization_vs_pbft_multi = theoretical_multilayer / divisor

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
            "chained_hotstuff": {
                "name": "Chained HotStuff",
                "theoretical": theoretical_chained_hotstuff,
                # Theoretical shadow only — actual count not tracked separately
                "actual": theoretical_chained_hotstuff,
                "complexity": "O(N)",
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

