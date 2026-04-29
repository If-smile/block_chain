"""
Robot / agent behaviour module: automated voting, proposal sending, and task scheduling.

- RobotAgent: pure-logic class (generates proposals/votes, resets state); no Socket.IO dependency.
- This module also provides async network-layer helpers that collaborate with socket_handlers via
  injected callbacks (handle_vote, finalize_consensus, …) to avoid circular imports.
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
    Robot-node behaviour agent (pure logic layer — no network sends).

    Responsibilities:
    - Generate proposal and vote messages for robot nodes based on the current view/phase.
    - Maintain and update the robot_node_states structure stored inside the session dict.

    Constraints:
    - No Socket.IO dependency (no sio, no emit calls).
    - No direct database or I/O calls.
    """

    # ==================== Robot state management ====================

    def reset_states_for_view_change(self, session: Dict[str, Any]) -> None:
        """Reset all robot-node vote flags on a view-change (identities are preserved)."""
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
        """Reset all robot-node vote flags at the start of a new round."""
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
        """Mark all non-Leader robot nodes as having received the current Proposal."""
        for robot_id in session.get("robot_nodes", []):
            if robot_id == proposer_id:
                continue
            session.setdefault("robot_node_states", {})
            state = session["robot_node_states"].setdefault(robot_id, {})
            state["received_pre_prepare"] = True

    # ==================== Proposal generation ====================

    def generate_proposal(
        self,
        session: Dict[str, Any],
        high_qc: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a Proposal (PRE-PREPARE) message for the current view's Leader (does not send).

        Returns:
            The Proposal message dict, or None if the Leader is not a robot node.
        """
        current_view = session["current_view"]
        last_view = session.get("last_pre_prepare_view")
        if last_view == current_view:
            # Proposal already generated for this view
            return None

        proposer_id = get_current_leader(session)
        if proposer_id not in session.get("robot_nodes", []):
            # Leader is a human node — frontend is responsible
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

        # Append to session history (pure state mutation)
        session["messages"]["pre_prepare"].append(message)

        return message

    # ==================== Vote generation ====================

    def generate_vote_for_robot(
        self,
        session: Dict[str, Any],
        robot_id: int,
        phase: str,
        value: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a single robot node's vote message for the given phase (does not send).

        Returns None if the node is the Root (Global Leader), which does not self-vote.
        """
        current_view = session["current_view"]
        node_info = get_topology_info(session, robot_id, current_view)
        target_id = node_info["parent_id"]

        # Root (Global Leader) does not vote to itself
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

        # Append to session history (pure state mutation)
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
        Generate vote messages for all robot nodes in the given phase (does not send).

        Note: view-change guards must be handled by the network-layer caller.
        """
        votes: List[Dict[str, Any]] = []
        leader_id = get_current_leader(session)

        for robot_id in session.get("robot_nodes", []):
            if robot_id == leader_id:
                # Global Leader does not send a regular vote to itself
                continue

            node_info = get_topology_info(session, robot_id, view)
            if node_info["role"] == "root":
                continue

            vote = self.generate_vote_for_robot(session, robot_id, phase, value)
            if vote is not None:
                votes.append(vote)

        return votes


# Module-level RobotAgent singleton (created after the class definition)
robot_agent = RobotAgent()


# ==================== Robot node creation and startup ====================

async def create_robot_nodes_and_start(
    session_id: str,
    robot_count: int,
    *,
    start_hotstuff_process_cb: Callable[[str], Awaitable[None]],
) -> None:
    """Create robot nodes and immediately start the HotStuff process.
    start_hotstuff_process_cb is injected by socket_handlers to avoid circular imports.
    """
    session = get_session(session_id)
    if not session:
        return
    # Simulation mode uses a much shorter delay to maximise throughput
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 1.0
    await asyncio.sleep(delay)
    print(f"Creating {robot_count} robot node(s)")
    for robot_id in range(robot_count):
        session["robot_nodes"].append(robot_id)
        connected_nodes[session_id].append(robot_id)
        print(f"Robot node {robot_id} created")
        session["robot_node_states"][robot_id] = {
            "received_pre_prepare": False,
            "received_prepare_count": 0,
            "received_commit_count": 0,
            "sent_prepare": False,
            "sent_commit": False,
        }
    print(f"Robot nodes ready — starting HotStuff consensus immediately")
    await start_hotstuff_process_cb(session_id)


# ==================== Robot vote triggering and sending ====================

async def trigger_robot_votes(
    session_id: str,
    view: int,
    phase: str,
    value: int,
    *,
    handle_vote_cb: Callable[[str, Dict[str, Any]], Awaitable[None]],
    finalize_consensus_cb: Callable[[str, str, str], Awaitable[None]],
) -> None:
    """Trigger robot nodes to send votes when entering a new phase.
    handle_vote and finalize_consensus are injected by socket_handlers.
    """
    print(f"Triggering robot auto-votes: session={session_id}, view={view}, phase={phase}")
    session = get_session(session_id)
    if not session:
        return
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 2.0
    await asyncio.sleep(delay)
    if session.get("current_view") != view:
        print(f"View changed from {view} to {session.get('current_view')} — cancelling auto-vote")
        return
    if phase == "decide":
        print(f"Entering Decide phase — finalising consensus directly: view={view}")
        await finalize_consensus_cb(session_id, "Consensus Success", f"View {view} consensus reached")
        return
    votes = robot_agent.generate_votes_for_phase(session, view, phase, value)
    for vote_msg in votes:
        # 1. Simulate forward drop: QC from Leader to Replica
        if not should_deliver_message(session_id):
            continue

        target_id = vote_msg["to"]
        node_info = get_topology_info(session, vote_msg["from"], view)
        target_sid = node_sockets.get(session_id, {}).get(target_id)
        count_message_sent(session_id, is_broadcast=False)

        # 2. Simulate reverse drop: Vote from Replica back to Leader
        delivered = should_deliver_message(session_id)

        if target_sid and delivered:
            await sio.emit("message_received", vote_msg, room=target_sid)
            role_name = "Group Leader" if node_info["role"] == "member" else "Global Leader"
            print(f"[Double-Layer HotStuff] Robot node {vote_msg['from']} ({node_info['role']}) → {role_name} {target_id}: VOTE({phase})")

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
    """Send the Leader's Proposal (HotStuff PRE-PREPARE).
    Timeout and prepare callbacks are injected by the caller.
    """
    session = get_session(session_id)
    if not session:
        return
    message = robot_agent.generate_proposal(session, highQC)
    if message is None:
        current_view = session.get("current_view", 0)
        proposer_id = get_current_leader(session)
        print(f"Leader {proposer_id} is not a robot node in view {current_view} — waiting for human action")
        return
    current_view = message["view"]
    proposer_id = message["from"]
    config = session["config"]
    n = config["nodeCount"]

    # Use the topology engine to find all Group Leaders (excluding the Global Leader itself)
    group_leaders: List[int] = []
    proposer_group_members: List[int] = []
    for node_id in range(n):
        info = get_topology_info(session, node_id, current_view)
        if info["role"] == "group_leader" and node_id != proposer_id:
            group_leaders.append(node_id)
        # Members in the Proposer's own group (parent_id == proposer_id) must receive the Proposal directly
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
                print(f"[Network sim] Proposal dropped (target: Group Leader {gl_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)")
    for gl_id in group_leaders:
        forward_message = message.copy()
        forward_message["from"] = gl_id
        forward_message["to"] = "group_members"

        # Find all members whose parent is this Group Leader
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
                    print(f"[Route] Node {gl_id} -> Node {member_id} (Role: member)")
                else:
                    print(f"[Network sim] Proposal forward dropped (target: Member {member_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)")
    # Proposer directly broadcasts to members in its own group to prevent proposal isolation
    if proposer_group_members:
        count_message_sent(session_id, is_broadcast=False, target_count=len(proposer_group_members))
        for member_id in proposer_group_members:
            member_sid = node_sockets.get(session_id, {}).get(member_id)
            if member_sid:
                if should_deliver_message(session_id):
                    await sio.emit("message_received", message, room=member_sid)
                    print(f"[Route] Node {proposer_id} -> Node {member_id} (Role: member, same group as root)")
                else:
                    print(
                        f"[Network sim] Proposal forward dropped (target: Member {member_id}, delivery rate: "
                        f"{session['config'].get('messageDeliveryRate', 100)}%)"
                    )

    # Broadcast to the whole session room for frontend animation display
    await sio.emit("message_received", message, room=session_id)
    print(
        f"[Double-Layer HotStuff] Global Leader {proposer_id} (view {current_view}) sent Proposal: "
        f"value={message['value']}, highQC.view={message['qc'].get('view') if message.get('qc') else None}"
    )
    print(f"[Double-Layer HotStuff] Proposal propagated: Global Leader → {len(group_leaders)} Group Leaders → Members")
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
    print(f"Session {session_id} view {current_view} entering Prepare phase")
    timeout_task = asyncio.create_task(handle_consensus_timeout_cb(session_id, current_view))
    session["timeout_task"] = timeout_task
    print(f"View {current_view} timeout watchdog started (View Change triggers on expiry)")
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
    """Automatically send Prepare-phase VOTEs for all robot nodes.
    handle_proposal_message_cb and handle_robot_prepare_cb are injected by the caller.
    """
    if not handle_proposal_message_cb or not handle_robot_prepare_cb:
        raise ValueError("robot_send_prepare_messages requires handle_proposal_message_cb and handle_robot_prepare_cb")
    session = get_session(session_id)
    if not session:
        return
    current_view = session["current_view"]
    proposal_msgs = [m for m in session["messages"]["pre_prepare"] if m.get("view") == current_view]
    if not proposal_msgs:
        print(f"View {current_view}: no Proposal found — robot nodes will not vote")
        return
    proposal_msg = proposal_msgs[-1]
    print(f"View {current_view}: robot nodes will send VOTE(prepare) after delay")
    is_simulation = session.get("config", {}).get("is_simulation", False)
    delay = 0.001 if is_simulation else 10.0
    await asyncio.sleep(delay)
    session = get_session(session_id)
    if not session:
        return
    if session["current_view"] != current_view:
        print(f"View changed ({current_view} → {session['current_view']}) — aborting vote send")
        return
    leader_id = get_current_leader(session, current_view)
    for robot_id in session.get("robot_nodes", []):
        if robot_id == leader_id:
            continue
        if session["robot_node_states"][robot_id].get("sent_prepare"):
            continue
        if not should_deliver_message(session_id):
            print(f"[Network sim] Node {robot_id} did not receive Proposal (dropped) — skipping vote")
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
    """Handle a robot node's Prepare-phase vote (double-layer HotStuff).
    handle_vote is injected by the caller.
    """
    session = get_session(session_id)
    if not session:
        return
    vote_message = robot_agent.generate_vote_for_robot(session, robot_id, "prepare", value)
    if vote_message is None:
        print(f"[Double-Layer HotStuff] Global Leader {robot_id} skips self-vote")
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
            print(f"[Double-Layer HotStuff] Robot node {robot_id} ({node_info['role']}) → {role_name} {target_id}: VOTE(prepare) [view {session['current_view']}]")
        else:
            print(f"[Double-Layer HotStuff] Target {target_id} offline — robot vote buffered")
        await handle_vote_cb(session_id, vote_message)
    else:
        print(
            f"[Network sim] Backend intercept: robot VOTE(prepare) dropped "
            f"(from={robot_id}, to={target_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)"
        )


async def schedule_robot_prepare(
    session_id: str,
    robot_id: int,
    value: int,
    *,
    handle_robot_prepare_cb: Callable[[str, int, int], Awaitable[None]],
) -> None:
    """Schedule a robot node to send its Prepare-phase vote after a short delay."""
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
        print(f"View changed ({current_view} → {session['current_view']}) — node {robot_id} aborts Prepare send")
        return
    if session.get("phase") != "prepare":
        print(f"Phase changed — node {robot_id} aborts Prepare send")
        return
    await handle_robot_prepare_cb(session_id, robot_id, value)


async def check_robot_nodes_ready_for_commit(session_id: str) -> None:
    """Placeholder: in HotStuff the Commit phase is driven by QC collection, not this check."""
    return


async def schedule_robot_commit(
    session_id: str,
    robot_id: int,
    value: int,
    *,
    handle_robot_commit_cb: Callable[[str, int, int], Awaitable[None]],
) -> None:
    """Schedule a robot node to send its Commit-phase vote after a delay."""
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
        print(f"Round changed ({current_round} → {session['current_round']}) — node {robot_id} aborts Commit send")
        return
    await handle_robot_commit_cb(session_id, robot_id, value)


async def handle_robot_commit(
    session_id: str,
    robot_id: int,
    value: int,
    *,
    handle_vote_cb: Callable[[str, Dict[str, Any]], Awaitable[None]],
) -> None:
    """Handle a robot node's Commit-phase vote (double-layer HotStuff).
    handle_vote is injected by the caller.
    """
    session = get_session(session_id)
    if not session:
        return
    vote_message = robot_agent.generate_vote_for_robot(session, robot_id, "commit", value)
    if vote_message is None:
        print(f"[Double-Layer HotStuff] Global Leader {robot_id} skips self-vote")
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
            print(f"[Double-Layer HotStuff] Robot node {robot_id} ({node_info['role']}) → {role_name} {target_id}: VOTE(commit)")
        else:
            print(f"[Double-Layer HotStuff] Target {target_id} offline — robot vote buffered")
        await handle_vote_cb(session_id, vote_message)
    else:
        print(
            f"[Network sim] Backend intercept: robot VOTE(commit) dropped "
            f"(from={robot_id}, to={target_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)"
        )

