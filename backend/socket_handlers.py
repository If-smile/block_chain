"""
Socket.IO event handlers and business-logic module.

Contains all Socket.IO event handlers and message-routing logic.
Automated robot/agent behaviour has been extracted into robot_agent.py
and is wired back via callbacks.  Refactored out of main.py for
modularity.
"""

from typing import Dict, Any, Optional, List
import uuid
import random
import asyncio
from datetime import datetime

# Persistence module
import database

# Global state and Socket.IO server (includes network stats and delivery probability)
from state import (
    sio,
    sessions,
    connected_nodes,
    node_sockets,
    get_session,
    should_deliver_message,
    count_message_sent,
)

# Consensus algorithm functions / pure-logic service layer
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

from consensus_service import ConsensusService
from robot_agent import (
    RobotAgent,
    create_robot_nodes_and_start,
    trigger_robot_votes,
    robot_send_pre_prepare,
    robot_send_prepare_messages,
    handle_robot_prepare,
    schedule_robot_prepare,
    check_robot_nodes_ready_for_commit,
    schedule_robot_commit,
    handle_robot_commit,
)

# Topology management
from topology_manager import (
    get_current_leader,
    get_topology_info,
    is_connection_allowed
)

# Data models
from models import SessionConfig, SessionInfo

# Service-layer singletons
consensus_service = ConsensusService()
robot_agent = RobotAgent()


# ==================== Session management ====================

def create_session(config: SessionConfig, is_simulation: bool = False) -> SessionInfo:
    """Create a new consensus session and kick off robot nodes."""
    session_id = str(uuid.uuid4())

    print(f"create_session - raw config:", config.dict())
    print(f"proposal content check at creation:", {
        'proposalContent': config.proposalContent,
        'hasProposalContent': config.proposalContent and config.proposalContent.strip(),
        'proposalValue': config.proposalValue
    })
    
    base_config = config.dict()
    # Tag the config so downstream logic can skip persistence and shorten timeouts
    if is_simulation:
        base_config["is_simulation"] = True

    session = {
        "config": base_config,
        "status": "waiting",
        "phase": "waiting",
        "phase_step": 0,
        "current_view": 0,          # HotStuff view counter (the protocol clock)
        "current_round": 1,         # Round number for message tagging and history replay (1-based)
        "start_view_of_round": 0,   # View at which the current round started (used to count view-changes)
        "leader_id": 0,             # Leader ID for the current view
        "connected_nodes": [],
        "robot_nodes": [],          # Automated robot node IDs
        "human_nodes": [],          # Human (potentially Byzantine) node IDs
        "robot_node_states": {},    # Per-robot state (tracks received messages)
        "timeout_task": None,       # asyncio Task handle for the view timeout
        "messages": {
            "pre_prepare": [],
            "prepare": [],
            "commit": [],
            "vote": [],
            "qc": [],
            "new_view": []          # NEW-VIEW messages
        },
        "node_states": {},          # Per-node persistent state {node_id: {lockedQC, prepareQC, currentView}}
        "pending_votes": {},        # {(view, phase, value): set(voter_ids)}
        "pending_new_views": {},    # {view: {node_id: new_view_msg}} NEW-VIEW messages collected by the leader
        "message_buffer": {},       # {view: [messages]} future-view message buffer (flat structure)
        "network_stats": {          # Communication-complexity counters
            "total_messages_sent": 0,   # Total network packets generated this round
            "phases_count": 0           # Number of HotStuff phase transitions
        },
        "consensus_result": None,
        "consensus_history": [],    # Per-round consensus snapshots
        "created_at": datetime.now().isoformat()
    }
    
    # Initialise per-node persistent state (required by HotStuff Safety)
    n = config.nodeCount
    for node_id in range(n):
        session["node_states"][node_id] = {
            "lockedQC": None,      # Highest locked QC (used in SafeNode check)
            "prepareQC": None,     # Highest prepared QC (used for HighQC selection in New-View)
            "currentView": 0,      # Node's current view (used for message validation)
            "highQC": None         # Highest QC seen so far (sent in NEW-VIEW messages)
        }
    session["leader_id"] = session["current_view"] % config.nodeCount
    
    sessions[session_id] = session
    connected_nodes[session_id] = []
    node_sockets[session_id] = {}

    # Persist initial session state to SQLite (skipped in simulation mode to avoid disk I/O)
    if not is_simulation:
        try:
            database.upsert_session(session_id, session)
        except Exception as e:
            print(f"[database] Failed to save initial session {session_id}: {e}")

    # Spawn robot nodes and immediately begin consensus
    # (start_hotstuff_process is defined in this module and injected as a callback)
    asyncio.create_task(
        create_robot_nodes_and_start(session_id, config.robotNodes, start_hotstuff_process_cb=start_hotstuff_process)
    )
    
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


# ==================== Socket.IO event handlers ====================

@sio.event
async def connect(sid, environ, auth):
    """Handle client connection."""
    print(f"Client connected: {sid}")

    # Extract session and node information from query-string parameters
    query = environ.get('QUERY_STRING', '')
    params = dict(item.split('=') for item in query.split('&') if '=' in item)
    
    session_id = params.get('sessionId')
    node_id = int(params.get('nodeId', 0))
    
    if session_id and session_id in sessions:
        # Store node ↔ socket-ID mapping
        if session_id not in node_sockets:
            node_sockets[session_id] = {}
        node_sockets[session_id][node_id] = sid

        # Add to the connected-nodes list
        if session_id not in connected_nodes:
            connected_nodes[session_id] = []
        if node_id not in connected_nodes[session_id]:
            connected_nodes[session_id].append(node_id)

            # Human nodes are treated as (potentially) Byzantine
            session = sessions[session_id]
            if node_id not in session["robot_nodes"]:
                session["human_nodes"].append(node_id)
                print(f"Human node {node_id} connected (Byzantine-capable)")
            else:
                print(f"Robot node {node_id} reconnected")

        session = sessions[session_id]

        # Send session configuration to the joining node
        config = session["config"]
        print(f"Sending session config to node {node_id}:", config)
        print(f"Proposal content check (backend):", {
            'proposalContent': config.get('proposalContent'),
            'hasProposalContent': config.get('proposalContent') and config.get('proposalContent').strip(),
            'proposalValue': config.get('proposalValue')
        })
        await sio.emit('session_config', config, room=sid)
        
        # Sync current consensus state so the newly connected node is up to date
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
        
        print(f"Node {node_id} synced state: View={current_view}, Phase={current_phase}, Step={current_step}, Leader={current_leader}")

        # Human nodes joining mid-round do not participate in the current round;
        # they only receive the session config and wait for the next round.
        print(f"Human node {node_id} joined — waiting for next consensus round")

        # Add node to the session's Socket.IO room
        await sio.enter_room(sid, session_id)

        # Broadcast updated connected-nodes list
        await sio.emit('connected_nodes', connected_nodes[session_id], room=session_id)

        print(f"Node {node_id} joined session {session_id}")

        # Start consensus if the required number of nodes is now connected
        await check_and_start_consensus(session_id)

@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    print(f"Client disconnected: {sid}")

    # Find and remove the node's connection record
    for session_id, nodes in node_sockets.items():
        for node_id, node_sid in nodes.items():
            if node_sid == sid:
                del nodes[node_id]
                if node_id in connected_nodes.get(session_id, []):
                    connected_nodes[session_id].remove(node_id)

                # Broadcast updated connected-nodes list
                await sio.emit('connected_nodes', connected_nodes[session_id], room=session_id)
                print(f"Node {node_id} left session {session_id}")
                break

@sio.event
async def send_prepare(sid, data):
    """Handle a Prepare vote (double-layer HotStuff: route to parent based on role)."""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    value = data.get('value')
    
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    
    # Determine vote target from topology (parent node in the two-layer tree)
    node_info = get_topology_info(session, node_id, current_view)
    target_id = node_info['parent_id']

    # Root (Global Leader) does not vote to itself
    if node_info['role'] == 'root':
        print(f"[Double-Layer HotStuff] Global Leader {node_id} skips self-vote")
        return

    target_sid = node_sockets.get(session_id, {}).get(target_id)

    # Build the VOTE message addressed to the parent node
    current_round = session.get("current_round", 1)
    vote_message = {
        "from": node_id,
        "to": target_id,
        "type": "vote",
        "value": value,
        "phase": "prepare",
        "view": current_view,
        "round": current_round,     # Tag with current round for history filtering
        "qc": data.get("qc"),
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "byzantine": data.get("byzantine", False)
    }

    session["messages"]["vote"].append(vote_message)

    # Unicast to parent — count as one sent message regardless of online status
    count_message_sent(session_id, is_broadcast=False)
    delivered = should_deliver_message(session_id)
    if target_sid:
        if delivered:
            await sio.emit('message_received', vote_message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[Double-Layer HotStuff] Node {node_id} ({node_info['role']}) → {role_name} {target_id}: VOTE(prepare)")
        else:
            print(f"[Network sim] Node {node_id} VOTE(prepare) dropped (target: {target_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)")
    else:
        print(f"[Double-Layer HotStuff] Target {target_id} offline — VOTE buffered")

    # Only accumulate the vote on the backend when the message is considered delivered
    if delivered:
        await handle_vote(session_id, vote_message)

@sio.event
async def send_commit(sid, data):
    """Handle a Commit vote (double-layer HotStuff: route to parent based on role)."""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    value = data.get('value')
    
    session = get_session(session_id)
    if not session:
        return
    
    current_view = session["current_view"]
    
    # Determine vote target from topology
    node_info = get_topology_info(session, node_id, current_view)
    target_id = node_info['parent_id']

    # Root (Global Leader) does not vote to itself
    if node_info['role'] == 'root':
        print(f"[Double-Layer HotStuff] Global Leader {node_id} skips self-vote")
        return

    target_sid = node_sockets.get(session_id, {}).get(target_id)

    # Build the VOTE message
    current_round = session.get("current_round", 1)
    vote_message = {
        "from": node_id,
        "to": target_id,
        "type": "vote",
        "value": value,
        "phase": "commit",
        "view": current_view,
        "round": current_round,     # Tag with current round
        "qc": data.get("qc"),
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "byzantine": data.get("byzantine", False)
    }

    session["messages"]["vote"].append(vote_message)

    # Unicast to parent — always count as one sent message
    count_message_sent(session_id, is_broadcast=False)
    delivered = should_deliver_message(session_id)
    if target_sid:
        if delivered:
            await sio.emit('message_received', vote_message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[Double-Layer HotStuff] Node {node_id} ({node_info['role']}) → {role_name} {target_id}: VOTE(commit)")
        else:
            print(f"[Network sim] Node {node_id} VOTE(commit) dropped (target: {target_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)")
    else:
        print(f"[Double-Layer HotStuff] Target {target_id} offline — VOTE buffered")

    # Only accumulate on the backend when delivered
    if delivered:
        await handle_vote(session_id, vote_message)

@sio.event
async def send_message(sid, data):
    """Handle a generic message (custom-message feature has been removed)."""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    message_type = data.get('type')
    value = data.get('value')
    target = data.get('target')
    
    session = get_session(session_id)
    if not session:
        return
    
    # Record the message
    message = {
        "from": node_id,
        "to": target,
        "type": message_type,
        "value": value,
        "phase": session.get("phase", "waiting"),
        "view": session.get("current_view", 0),    # HotStuff view (used by core logic)
        "round": session.get("current_round", 1),  # Round tag for history filtering and UI
        "qc": data.get("qc"),                      # Quorum Certificate (if any)
        "timestamp": datetime.now().isoformat(),
        "tampered": False
    }

    # Store in the appropriate message bucket
    if message_type == "prepare":
        session["messages"]["prepare"].append(message)
    elif message_type == "commit":
        session["messages"]["commit"].append(message)
    elif message_type == "vote":
        # HotStuff vote messages go into the vote list
        session["messages"]["vote"].append(message)
    else:
        # Catch-all for other message types
        if "other" not in session["messages"]:
            session["messages"]["other"] = []
        session["messages"]["other"].append(message)

    # Route by message type (double-layer HotStuff: votes go to the parent node)
    if message_type == "vote":
        current_view = session.get("current_view", 0)

        # Determine target from topology
        node_info = get_topology_info(session, node_id, current_view)
        target_id = node_info['parent_id']

        # Root (Global Leader) does not vote to itself
        if node_info['role'] == 'root':
            print(f"[Double-Layer HotStuff] Global Leader {node_id} skips self-vote")
            return

        # Update message destination
        message["to"] = target_id

        target_sid = node_sockets.get(session_id, {}).get(target_id)
        # Unicast to parent — always count as one sent message
        count_message_sent(session_id, is_broadcast=False)
        if target_sid:
            await sio.emit('message_received', message, room=target_sid)
            role_name = "Group Leader" if node_info['role'] == 'member' else "Global Leader"
            print(f"[Double-Layer HotStuff] Node {node_id} ({node_info['role']}) → {role_name} {target_id}: VOTE")
        else:
            print(f"[Double-Layer HotStuff] Target {target_id} offline — VOTE buffered")
        await handle_vote(session_id, message)
    else:
        # Non-vote messages: broadcast to all nodes
        if should_deliver_message(session_id):
            await sio.emit('message_received', message, room=session_id)
            print(f"Node {node_id} message sent (delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)")
        else:
            print(f"Node {node_id} message dropped (delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)")

@sio.event
async def choose_normal_consensus(sid, data):
    """Handle a human node choosing to participate honestly (delegates to robot mode)."""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')
    
    session = get_session(session_id)
    if not session:
        return
    
    # Switch this human node to robot-agent mode
    print(f"Human node {node_id} chose normal consensus — switching to robot-agent mode")

    # Remove from human list and add to robot list for this round
    if node_id in session["human_nodes"]:
        session["human_nodes"].remove(node_id)

    if node_id not in session["robot_nodes"]:
        session["robot_nodes"].append(node_id)

        # Initialise robot state for this node
        session["robot_node_states"][node_id] = {
            "received_pre_prepare": True,
            "received_prepare_count": len([m for m in session["messages"]["prepare"] if m["from"] != node_id]),
            "received_commit_count": len([m for m in session["messages"]["commit"] if m["from"] != node_id]),
            "sent_prepare": False,
            "sent_commit": False
        }
    
    # Automatically send the appropriate message for the current phase
    # (handle_vote is injected as a callback for robot_agent)
    config = session["config"]

    async def _prep_cb(s, r, v):
        await handle_robot_prepare(s, r, v, handle_vote_cb=handle_vote)

    async def _commit_cb(s, r, v):
        await handle_robot_commit(s, r, v, handle_vote_cb=handle_vote)

    if session["phase"] == "prepare" and node_id != 0:
        session["robot_node_states"][node_id]["sent_prepare"] = True
        asyncio.create_task(
            schedule_robot_prepare(session_id, node_id, config["proposalValue"], handle_robot_prepare_cb=_prep_cb)
        )
    elif session["phase"] == "commit":
        session["robot_node_states"][node_id]["sent_commit"] = True
        asyncio.create_task(
            schedule_robot_commit(session_id, node_id, config["proposalValue"], handle_robot_commit_cb=_commit_cb)
        )

@sio.event
async def choose_byzantine_attack(sid, data):
    """Handle a human node choosing Byzantine (malicious) behaviour."""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')

    print(f"Human node {node_id} chose Byzantine attack mode")
    # No extra action needed — the node stays in human_nodes and behaves adversarially

@sio.event
async def ping(sid, data):
    """Respond to a Ping message with a Pong."""
    session_id = data.get('sessionId')
    node_id = data.get('nodeId')

    pong_message = {
        "from": "server",
        "to": node_id,
        "type": "pong",
        "value": None,
        "phase": "ping",
        "timestamp": datetime.now().isoformat(),
        "tampered": False,
        "customContent": f"Server Pong to node {node_id}"
    }

    await sio.emit('message_received', pong_message, room=session_id)
    print(f"Node {node_id} pinged — server responded with Pong")


# ==================== Message-processing functions ====================

async def handle_proposal_message(session_id: str, proposal_msg: Dict[str, Any], node_id: int) -> bool:
    """
    Process a Proposal message received by a replica (HotStuff PRE-PREPARE step).

    Runs the SafeNode predicate check; if it passes, triggers a Prepare vote.

    Args:
        session_id:   Session identifier.
        proposal_msg: The incoming Proposal message dict.
        node_id:      ID of the replica receiving the proposal.

    Returns:
        True if SafeNode passed and a vote was sent, False otherwise.
    """
    session = get_session(session_id)
    if not session:
        return False

    result = consensus_service.handle_proposal(session, proposal_msg, node_id)

    if not result["accepted"]:
        # Buffered or rejected — log the reason
        reason = result.get("reason")
        if result.get("buffered"):
            print(f"Node {node_id}: Proposal buffered — {reason}")
        else:
            print(f"Node {node_id}: Proposal rejected — {reason}")
        return False

    proposal_view = proposal_msg.get("view", -1)
    proposal_value = proposal_msg.get("value")
    print(f"Node {node_id}: SafeNode passed — sending Vote (view={proposal_view}, value={proposal_value})")

    # Robot nodes vote automatically; human nodes are triggered by the frontend
    if node_id in session.get("robot_nodes", []):
        await handle_robot_prepare(session_id, node_id, proposal_value, handle_vote_cb=handle_vote)
        return True

    return True

async def handle_qc_message(session_id: str, qc_msg: Dict[str, Any], node_id: int):
    """
    Process a QC message received by a node (HotStuff phase advancement).

    Updates the node's lockedQC when a Commit-phase QC is received.
    Updates prepareQC (used for New-View HighQC selection) on any QC.

    Args:
        session_id: Session identifier.
        qc_msg:     The incoming QC message dict.
        node_id:    ID of the node receiving the QC.
    """
    session = get_session(session_id)
    if not session:
        return

    consensus_service.handle_qc_for_node(session, qc_msg, node_id)

    qc = qc_msg.get("qc", {})
    qc_phase = qc.get("phase", "")
    qc_view = qc.get("view", -1)
    if qc_phase == "commit":
        print(f"Node {node_id}: Commit QC received (view={qc_view}) — lockedQC updated")

async def handle_vote(session_id: str, vote_message: Dict[str, Any]):
    """
    Double-layer HotStuff vote handler: supports hierarchical vote aggregation.

    Flow:
    1. Member → Group Leader : regular nodes vote to their local Group Leader
    2. Group Leader → Global Leader : once the local quorum is reached, the Group
       Leader sends a weighted GroupVote to the Global Leader
    3. Global Leader : collects GroupVotes, checks the global weight threshold,
       and generates the final QC

    Message buffering: if vote.view > current_view the message is buffered and
    re-processed after the view-change completes.
    """
    session = get_session(session_id)
    if not session:
        return

    view = vote_message.get("view", session.get("current_view", 0))
    phase = vote_message.get("phase", "prepare")
    value = vote_message.get("value")

    result = consensus_service.handle_vote(session, vote_message)
    status = result.get("status")

    if status == "buffered":
        print(f"Vote view {view} > current view {session.get('current_view', 0)} — buffered")
        return
    if status == "ignored":
        print(f"Ignored stale or invalid-role vote: view={view}, phase={phase}")
        return

    # If the Service produced a GroupVote, route it to the Global Leader at the network layer
    group_vote = result.get("group_vote")
    if group_vote:
        global_leader_id = group_vote["to"]
        global_leader_sid = node_sockets.get(session_id, {}).get(global_leader_id)
        count_message_sent(session_id, is_broadcast=False)
        if global_leader_sid:
            if should_deliver_message(session_id):
                await sio.emit("message_received", group_vote, room=global_leader_sid)
                print(
                    f"[Double-Layer HotStuff] Group Leader {group_vote['from']} → Global Leader {global_leader_id}: GroupVote (weight={group_vote.get('weight')})"
                )
            else:
                print(
                    f"[Network sim] Group Leader {group_vote['from']} GroupVote dropped (target: Global Leader {global_leader_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)"
                )

    # If a QC was produced, broadcast it via the two-layer topology and advance the phase
    qc_message = result.get("qc_message")
    routing = result.get("routing")
    if qc_message and routing:
        global_leader_id = routing["global_leader"]
        group_leaders = routing["group_leaders"]
        members_by_group_leader = routing["members_by_group_leader"]

        n = session["config"]["nodeCount"]

        # Global Leader -> Group Leaders
        if group_leaders:
            count_message_sent(session_id, is_broadcast=False, target_count=len(group_leaders))
        for gl_id in group_leaders:
            gl_sid = node_sockets.get(session_id, {}).get(gl_id)
            if gl_sid:
                if should_deliver_message(session_id):
                    await sio.emit("message_received", qc_message, room=gl_sid)
                else:
                    print(
                        f"[Network sim] QC dropped (target: Group Leader {gl_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)"
                    )

        # Group Leaders -> Members
        for gl_id, members in members_by_group_leader.items():
            forward_message = qc_message.copy()
            forward_message["from"] = gl_id
            forward_message["to"] = "group_members"

            target_member_count = max(len(members), 0)
            if target_member_count > 0:
                count_message_sent(
                    session_id, is_broadcast=False, target_count=target_member_count
                )

            for member_id in members:
                if member_id < 0 or member_id >= n:
                    continue
                member_sid = node_sockets.get(session_id, {}).get(member_id)
                if member_sid:
                    if should_deliver_message(session_id):
                        await sio.emit("message_received", forward_message, room=member_sid)
                    else:
                        print(
                            f"[Network sim] QC forward dropped (target: Member {member_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)"
                        )

        # Also broadcast to the whole room so the frontend can display it
        await sio.emit("message_received", qc_message, room=session_id)

        await sio.emit(
            "phase_update",
            {
                "phase": qc_message.get("next_phase"),
                "step": session.get("phase_step", 0),
                "leader": global_leader_id,
                "view": qc_message.get("view"),
            },
            room=session_id,
        )

        print(
            f"[Double-Layer HotStuff] Global Leader {global_leader_id} generated {phase} QC → entering {qc_message.get('next_phase')} phase (view={view})"
        )
        print(
            f"[Double-Layer HotStuff] QC propagated: Global Leader → {len(group_leaders)} Group Leaders → Members"
        )

        # All nodes update their local QC state
        consensus_service.handle_qc_for_all_nodes(session, qc_message)

        # Drive the next HotStuff phase automatically
        next_phase = qc_message.get("next_phase")
        if next_phase == "decide":
            await finalize_consensus(
                session_id, "Consensus Success", f"View {view} consensus reached"
            )
        else:
            try:
                asyncio.create_task(
                    trigger_robot_votes(
                        session_id,
                        qc_message.get("view"),
                        next_phase,
                        qc_message["qc"]["value"],
                        handle_vote_cb=handle_vote,
                        finalize_consensus_cb=finalize_consensus,
                    )
                )
            except RuntimeError as e:
                print(f"Failed to schedule trigger_robot_votes: {e}")


# ==================== Consensus logic ====================

async def check_and_start_consensus(session_id: str):
    """Start consensus if all required nodes are now connected."""
    session = get_session(session_id)
    if not session:
        return
    
    config = session["config"]
    connected_count = len(connected_nodes.get(session_id, []))
    
    if connected_count >= config["nodeCount"]:
        await start_consensus(session_id)

async def start_consensus(session_id: str):
    """
    Initialise the first round of HotStuff consensus.

    For View 0 the Leader sends a Proposal directly without a preceding New-View.
    """
    session = get_session(session_id)
    if not session:
        return
    
    session["status"] = "running"
    session["phase"] = "new-view"   # First HotStuff phase
    session["phase_step"] = 0

    print(f"Session {session_id}: starting HotStuff consensus (View 0)")

    # Notify all nodes to enter the new-view phase
    await sio.emit('phase_update', {
        "phase": "new-view",
        "step": 0,
        "leader": session["leader_id"],
        "view": session["current_view"]
    }, room=session_id)

    async def _prep_cb(s, r, v):
        await handle_robot_prepare(s, r, v, handle_vote_cb=handle_vote)
    await robot_send_pre_prepare(
        session_id,
        highQC=None,
        handle_consensus_timeout_cb=handle_consensus_timeout,
        handle_proposal_message_cb=handle_proposal_message,
        handle_robot_prepare_cb=_prep_cb,
    )

async def start_prepare_phase(session_id: str):
    """Enter the Prepare phase."""
    session = get_session(session_id)
    if not session:
        return
    
    session["phase"] = "prepare"
    session["phase_step"] = 1
    
    config = session["config"]
    
    # Notify all nodes to enter the Prepare phase
    await sio.emit('phase_update', {
        "phase": "prepare",
        "step": 1,
        "isMyTurn": True
    }, room=session_id)

    print(f"Session {session_id} entered Prepare phase")

async def check_prepare_phase(session_id: str):
    """Check whether the Prepare phase has collected enough votes to advance."""
    session = get_session(session_id)
    if not session:
        return
    
    config = session["config"]
    prepare_messages = session["messages"]["prepare"]
    
    # f = floor((n-1)/3); quorum threshold = 2f+1
    n = config["nodeCount"]
    f = (n - 1) // 3
    required_correct_messages = 2 * f + 1

    # Count distinct nodes that sent the correct value
    correct_nodes = set()
    for msg in prepare_messages:
        if msg.get("value") == config["proposalValue"]:
            correct_nodes.add(msg["from"])

    print(f"Prepare phase check — total nodes: {n}, faulty tolerance: {f}")
    print(f"Prepare phase check — required: {required_correct_messages}, received: {len(correct_nodes)}")
    print(f"Prepare phase check — correct-vote nodes: {correct_nodes}")

    if len(correct_nodes) >= required_correct_messages:
        print(f"Prepare phase complete ({len(correct_nodes)} correct votes) — advancing to Commit phase")
        await start_commit_phase(session_id)
    else:
        print(f"Prepare phase waiting — still need {required_correct_messages - len(correct_nodes)} more correct votes")

async def start_commit_phase(session_id: str):
    """Enter the Commit phase."""
    session = get_session(session_id)
    if not session:
        return
    
    session["phase"] = "commit"
    session["phase_step"] = 2
    
    # Notify all nodes to enter the Commit phase
    await sio.emit('phase_update', {
        "phase": "commit",
        "step": 2,
        "isMyTurn": True
    }, room=session_id)

    print(f"Session {session_id} entered Commit phase")

    # Placeholder — in HotStuff the phase is driven by QC, not by this check
    await check_robot_nodes_ready_for_commit(session_id)

async def check_commit_phase(session_id: str):
    """Check whether the Commit phase has reached a decision."""
    session = get_session(session_id)
    if not session:
        return
    
    config = session["config"]
    commit_messages = session["messages"]["commit"]
    
    # f = floor((n-1)/3)
    n = config["nodeCount"]
    f = (n - 1) // 3

    # Tally correct vs. incorrect votes from distinct nodes
    correct_nodes = set()
    error_nodes = set()

    for msg in commit_messages:
        if msg.get("value") == config["proposalValue"]:
            correct_nodes.add(msg["from"])
        else:
            error_nodes.add(msg["from"])

    print(f"Commit phase check — total nodes: {n}, faulty tolerance: {f}")
    print(f"Commit phase check — correct votes: {len(correct_nodes)}, incorrect votes: {len(error_nodes)}")
    print(f"Commit phase check — correct-vote nodes: {correct_nodes}")
    print(f"Commit phase check — incorrect-vote nodes: {error_nodes}")
    print(f"Commit phase check — thresholds: success={2*f+1}, failure={f+1}")

    if len(correct_nodes) >= 2 * f + 1:
        print(f"Consensus SUCCESS — {len(correct_nodes)} correct votes (needed {2*f+1})")
        await finalize_consensus(session_id, "Consensus Success", f"Received {len(correct_nodes)} valid messages")
    elif len(error_nodes) >= f + 1:
        print(f"Consensus FAILED — {len(error_nodes)} incorrect votes (needed {f+1})")
        await finalize_consensus(session_id, "Consensus Failed", f"Received {len(error_nodes)} invalid messages")
    else:
        print(f"Commit phase waiting — correct: {len(correct_nodes)}, incorrect: {len(error_nodes)}")

async def finalize_consensus(session_id: str, status: str = "Consensus Completed", description: str = "Consensus completed"):
    """
    Finalise consensus (HotStuff Decide phase).

    Note: in HotStuff, entering the Decide phase means consensus is reached for
    this value.  Subsequent proposals require a new View (via New-View mechanism).
    """
    session = get_session(session_id)
    if not session:
        return

    current_view = session["current_view"]
    if session.get("consensus_finalized_view") == current_view:
        print(f"View {current_view} already finalised — skipping duplicate call")
        return

    # Cancel the view timeout task (network-layer side-effects remain the network's responsibility)
    if session.get("timeout_task"):
        session["timeout_task"].cancel()
        print(f"View {current_view} finalised — timeout task cancelled")

    # Delegate result computation and stats to ConsensusService
    result = consensus_service.finalize_consensus_state(session, status, description)
    consensus_result = result["consensus_result"]
    history_item = result["history_item"]

    # Console reporting is done inside the Service; here we only broadcast and persist
    print(f"Broadcasting consensus result: {consensus_result}")
    await sio.emit("consensus_result", consensus_result, room=session_id)
    print(f"Consensus result sent to room: {session_id}")

    await sio.emit(
        "phase_update",
        {
            "phase": "completed",
            "step": 4,
            "isMyTurn": False,
        },
        room=session_id,
    )

    print(f"Session {session_id} view {session['current_view']} consensus done: {status}")

    is_simulation = session.get("config", {}).get("is_simulation", False)

    if not is_simulation:
        # Demo mode only: persist to database and schedule the next round
        try:
            database.append_history(session_id, history_item)
            database.upsert_session(session_id, session)
        except Exception as e:
            print(f"[database] Save failed: {e}")

        print(f"Round complete — next round starts in 10 seconds...")
        asyncio.create_task(start_next_round(session_id))
    else:
        # Simulation mode: break the chain — never trigger a next round or DB write
        print(f"[Simulation] Round complete — ghost task discarded.")

async def handle_consensus_timeout(session_id: str, view: int):
    """
    Handle a consensus timeout (HotStuff View-Change mechanism).

    A timeout is NOT a failure — it triggers a View Change:
    1. All nodes send NEW-VIEW messages to the Next Leader.
    2. The Next Leader collects 2f+1 NEW-VIEW messages and picks the HighQC.
    3. Consensus continues in the new view.

    Args:
        session_id: Session identifier.
        view:       The view number that timed out.
    """
    # Simulation mode uses a shorter timeout to quickly detect severe packet loss
    session = get_session(session_id)
    if not session:
        return
    is_simulation = session.get("config", {}).get("is_simulation", False)
    timeout_seconds = 0.5 if is_simulation else 40.0
    await asyncio.sleep(timeout_seconds)
    
    session = get_session(session_id)
    if not session:
        return
    
    # Only trigger if still in the same view and not yet finalised
    if session["current_view"] == view and session["status"] == "running":
        print(f"View {view} timed out (no consensus after {timeout_seconds}s) — triggering View Change")

        session["timeout_task"] = None

        # Trigger View Change (HotStuff Liveness guarantee)
        await trigger_view_change(session_id, view)

async def process_message_buffer(session_id: str, view: int):
    """
    Drain the message buffer for the given view and re-process each buffered message.

    Args:
        session_id: Session identifier.
        view:       The view whose buffered messages should be re-processed.
    """
    session = get_session(session_id)
    if not session:
        return
    
    buffer = session.get("message_buffer", {})
    if not buffer:
        return
    
    print(f"Processing buffered messages for view {view}...")

    for node_id, node_buffer in buffer.items():
        if view not in node_buffer:
            continue

        messages = node_buffer[view]
        print(f"Node {node_id} has {len(messages)} buffered message(s) for view {view}")

        for buffered_msg in messages:
            msg_type = buffered_msg.get("type")
            msg = buffered_msg.get("msg")

            if msg_type == "proposal":
                await handle_proposal_message(session_id, msg, node_id)
            elif msg_type == "vote":
                await handle_vote(session_id, msg)

        # Clear processed messages
        del node_buffer[view]

    print(f"Buffered messages for view {view} processed")

async def trigger_view_change(session_id: str, old_view: int):
    """
    Trigger a View Change (HotStuff New-View mechanism).

    All nodes send NEW-VIEW messages to the Next Leader, each carrying their
    highest prepareQC.  Once the leader collects 2f+1 NEW-VIEW messages it
    selects the highest HighQC and sends a new Proposal.
    """
    session = get_session(session_id)
    if not session:
        return
    
    new_view = old_view + 1
    n = session["config"]["nodeCount"]
    next_leader_id = get_current_leader(session, new_view)
    
    print(f"View Change: view {old_view} → view {new_view} (Next Leader: {next_leader_id})")

    # Advance the session view
    session["current_view"] = new_view
    session["leader_id"] = next_leader_id

    # Reset all robot-node vote states for the new view
    print(f"[View Change] Resetting robot node vote states...")
    robot_agent.reset_states_for_view_change(session)
    for robot_id in session.get("robot_nodes", []):
        print(f"  Robot node {robot_id}: vote state reset")

    # Every node sends a NEW-VIEW message to the Next Leader
    for node_id in range(n):
        node_state = session["node_states"].get(node_id, {})
        highQC = node_state.get("highQC")   # This node's highest prepareQC

        current_round = session.get("current_round", 1)
        new_view_msg = {
            "from": node_id,
            "to": next_leader_id,
            "type": "new_view",
            "view": new_view,
            "old_view": old_view,
            "round": current_round,     # Tag with current round
            "highQC": highQC,           # Carry the highest known QC
            "timestamp": datetime.now().isoformat()
        }
        
        session["messages"]["new_view"].append(new_view_msg)
        
        # Robot nodes are handled in-process; human nodes receive via WebSocket
        if node_id in session.get("robot_nodes", []):
            print(f"Node {node_id}: NEW-VIEW → Next Leader {next_leader_id} (highQC.view={highQC.get('view') if highQC else None})")
        else:
            node_sid = node_sockets.get(session_id, {}).get(node_id)
            if node_sid:
                if should_deliver_message(session_id):
                    await sio.emit('message_received', new_view_msg, room=node_sid)
                else:
                    print(f"[Network sim] Node {node_id} NEW-VIEW dropped (target: Next Leader {next_leader_id}, delivery rate: {session['config'].get('messageDeliveryRate', 100)}%)")

        # Leader does not send NEW-VIEW to itself
        if node_id == next_leader_id:
            continue
        
        pending_new_views = session.setdefault("pending_new_views", {})
        if new_view not in pending_new_views:
            pending_new_views[new_view] = {}
        pending_new_views[new_view][node_id] = new_view_msg
        
        # Count each NEW-VIEW message sent (robot and human alike)
        count_message_sent(session_id, is_broadcast=False)

    # Notify all nodes to enter the new-view phase
    await sio.emit('phase_update', {
        "phase": "new-view",
        "step": 0,
        "leader": next_leader_id,
        "view": new_view
    }, room=session_id)

    # Check whether the Next Leader has already collected enough NEW-VIEW messages
    await start_new_view_consensus(session_id, new_view)

    # Drain the message buffer for the new view now that the view-change is complete.
    # Messages are processed in the correct view context only after the switch.
    buffer = session.get("message_buffer", {})
    if new_view in buffer:
        buffered_votes = buffer[new_view]
        print(f"View {new_view} buffer has {len(buffered_votes)} vote message(s) — re-processing")
        for vote_msg in buffered_votes:
            await handle_vote(session_id, vote_msg)
        del buffer[new_view]

async def start_next_round(session_id: str):
    """Start the next consensus round (demo mode only)."""
    session = get_session(session_id)
    if not session:
        return
    if session.get("config", {}).get("is_simulation", False):
        return  # Ultimate guard: simulation mode must never trigger a next round
    # Demo mode: 10-second pause between rounds
    await asyncio.sleep(10.0)
    
    session = get_session(session_id)
    if not session:
        return
    
    # Advance round and view counters
    session["current_round"] += 1
    session["current_view"] += 1
    current_round = session["current_round"]
    # Record the starting view of this round (used to count view-changes per round)
    session["start_view_of_round"] = session["current_view"]
    # Update leader for the new view
    session["leader_id"] = get_current_leader(session)

    # Reset session state for the new round
    session["status"] = "running"
    session["phase"] = "pre-prepare"
    session["phase_step"] = 0
    session["consensus_result"] = None
    # Reset per-round network stats
    session["network_stats"] = {
        "total_messages_sent": 0,
        "phases_count": 0
    }

    # Message history is intentionally kept cumulative across rounds;
    # the `round` field on each message is used to filter by round.

    # Persist node identity across rounds — do NOT reset robot_nodes / human_nodes.
    # A human node that chose "Normal Consensus" in round 1 should stay in robot mode
    # for subsequent rounds; a human node that stayed in "Human Mode" should remain so.
    print(f"Round {current_round} start — preserving node identities")
    print(f"Round {current_round} — robot nodes: {session['robot_nodes']}")
    print(f"Round {current_round} — human nodes: {session['human_nodes']}")

    # Reset robot-node vote states (identity preserved; only vote flags reset)
    robot_agent.reset_states_for_new_round(session)

    print(f"Session {session_id} starting round {current_round}")

    # Notify all nodes (including waiting human nodes) that a new round has started
    await sio.emit('new_round', {
        "round": current_round,
        "view": session["current_view"],
        "leader": session["leader_id"],
        "phase": "pre-prepare",
        "step": 0
    }, room=session_id)
    
    # Notify all nodes to enter the pre-prepare phase
    await sio.emit('phase_update', {
        "phase": "pre-prepare",
        "step": 0,
        "isMyTurn": False
    }, room=session_id)

    print(f"Round {current_round} started — all nodes (including newly joined human nodes) may now participate")

    # Persist the new-round state (skipped in simulation mode)
    if not session.get("config", {}).get("is_simulation"):
        try:
            database.upsert_session(session_id, session)
        except Exception as e:
            print(f"[database] Failed to save new-round session state: session_id={session_id}, error={e}")

    # Robot proposer sends pre-prepare message
    # Note: in HotStuff, subsequent proposals should ideally go through View Change,
    # but this simpler "next round" path is kept for the demo multi-round flow.
    async def _prep_cb(s, r, v):
        await handle_robot_prepare(s, r, v, handle_vote_cb=handle_vote)
    await robot_send_pre_prepare(
        session_id,
        highQC=None,
        handle_consensus_timeout_cb=handle_consensus_timeout,
        handle_proposal_message_cb=handle_proposal_message,
        handle_robot_prepare_cb=_prep_cb,
    )

async def broadcast_to_online_nodes(session_id: str, event: str, data: Any):
    """Broadcast an event only to connected human nodes (robot nodes are handled in-process)."""
    session = get_session(session_id)
    if not session:
        return

    if session_id in node_sockets:
        for node_id, sid in node_sockets[session_id].items():
            if node_id in session["human_nodes"]:
                await sio.emit(event, data, room=sid)

    # Robot nodes do not receive WebSocket messages — they are driven by backend logic


async def start_hotstuff_process(session_id: str):
    """
    Start the HotStuff consensus process (called as a callback from robot_agent).

    For View 0 the Leader sends a Proposal directly without a preceding New-View.
    """
    session = get_session(session_id)
    if not session:
        return
    
    # Set initial session state
    session["status"] = "running"
    session["phase"] = "new-view"   # First HotStuff phase
    session["phase_step"] = 0
    # Record the starting view for this round (used to count view-changes)
    if "start_view_of_round" not in session:
        session["start_view_of_round"] = session["current_view"]

    # Notify all nodes to enter the new-view phase
    await sio.emit('phase_update', {
        "phase": "new-view",
        "step": 0,
        "leader": session["leader_id"],
        "view": session["current_view"]
    }, room=session_id)

    print(f"Session {session_id}: starting HotStuff consensus (view {session['current_view']})")
    
    async def _prep_cb(s, r, v):
        await handle_robot_prepare(s, r, v, handle_vote_cb=handle_vote)
    await robot_send_pre_prepare(
        session_id,
        highQC=None,
        handle_consensus_timeout_cb=handle_consensus_timeout,
        handle_proposal_message_cb=handle_proposal_message,
        handle_robot_prepare_cb=_prep_cb,
    )

async def start_new_view_consensus(session_id: str, view: int):
    """
    Start consensus for a new view (HotStuff New-View mechanism).

    If the leader has already collected 2f+1 NEW-VIEW messages, it selects the
    highest HighQC and sends a Proposal for the new view.
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
        print(f"View {view}: Leader {leader_id} has {len(pending_new_views)}/{threshold} NEW-VIEW messages — waiting for more")
        return

    # Select the highest HighQC from all received NEW-VIEW messages (core of New-View)
    highQC = None
    max_view = -1
    for node_id, new_view_msg in pending_new_views.items():
        qc = new_view_msg.get("highQC")
        if qc:
            qc_view = qc.get("view", -1)
            if qc_view > max_view:
                max_view = qc_view
                highQC = qc
    
    print(f"View {view}: Leader {leader_id} selected HighQC (view={max_view}) — sending Proposal")

    # If the leader is a robot node, send the Proposal automatically
    if leader_id in session.get("robot_nodes", []):
        async def _prep_cb(s, r, v):
            await handle_robot_prepare(s, r, v, handle_vote_cb=handle_vote)
        await robot_send_pre_prepare(
            session_id,
            highQC,
            handle_consensus_timeout_cb=handle_consensus_timeout,
            handle_proposal_message_cb=handle_proposal_message,
            handle_robot_prepare_cb=_prep_cb,
        )
    else:
        print(f"View {view}: Leader {leader_id} is a human node — waiting for manual Proposal")

