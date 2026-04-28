"""
FastAPI application entry point.

This file is responsible for:
- Initialising the FastAPI application
- Configuring CORS
- Creating the Socket.IO server and ASGI app
- Defining HTTP routes
- Starting the server
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any
from pydantic import BaseModel
import socketio
import asyncio
import time

# Global state and Socket.IO server
from state import sio, sessions, connected_nodes, node_sockets, get_session

# Data models
from models import SessionConfig

# Business logic
from socket_handlers import create_session
from topology_manager import get_topology_info, is_connection_allowed

# Persistence module
import database

# Create FastAPI application
app = FastAPI(title="分布式HotStuff共识系统", version="1.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create ASGI app (sio imported from state module)
socket_app = socketio.ASGIApp(sio, app)

# Import Socket.IO event handlers (registers all @sio.event decorators)
import socket_handlers


# ==================== Startup: restore persisted sessions ====================

@app.on_event("startup")
async def on_startup():
    """Initialise SQLite on startup and restore previously persisted session state."""
    database.init_db()

    # Load all session states from the database
    persisted_sessions = database.load_all_sessions()
    print(f"[startup] Loaded {len(persisted_sessions)} session(s) from SQLite")

    for session_id, state in persisted_sessions.items():
        # Defensive: skip malformed entries
        if not isinstance(state, dict):
            continue

        # Running sessions cannot be resumed after restart — reset to waiting
        if state.get("status") == "running":
            state["status"] = "waiting"
            state["phase"] = "waiting"
            state["phase_step"] = 0

        # Restore consensus history from the history table
        history_items = database.load_history(session_id)
        state["consensus_history"] = history_items

        # Restore into the global in-memory sessions dict
        sessions[session_id] = state

        # Restore connected-node list (empty list if not present)
        connected_nodes[session_id] = state.get("connected_nodes", [])
        # WebSocket connections cannot be persisted — clients must reconnect
        node_sockets[session_id] = {}

    print("[startup] Session state restored from SQLite into memory")


# ==================== HTTP routes & request models ====================


class SimulationRequest(BaseModel):
    """Request body for the Monte Carlo simulation endpoint."""
    config: Dict[str, Any]
    rounds: int = 1000


@app.post("/api/sessions")
async def create_consensus_session(config: SessionConfig):
    """Create a new consensus session."""
    try:
        session_info = create_session(config)
        return session_info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/simulate")
async def run_simulation(request: SimulationRequest):
    """
    Monte Carlo headless simulation endpoint.

    Runs multiple consensus rounds in headless mode for the given configuration
    and returns aggregated reliability statistics.
    """
    config_data = dict(request.config or {})

    # Basic parameter validation
    if "nodeCount" not in config_data:
        raise HTTPException(status_code=400, detail="config.nodeCount is required")
    node_count = config_data["nodeCount"]
    faulty_nodes = config_data.get("faultyNodes", 0)

    # Derive robotNodes from nodeCount/faultyNodes if not explicitly provided
    if "robotNodes" not in config_data:
        config_data["robotNodes"] = max(node_count - faulty_nodes, 0)

    # Force-disable malicious proposer in simulation mode
    config_data["maliciousProposer"] = False

    # Validate round count
    rounds = request.rounds or 1000
    if rounds <= 0:
        raise HTTPException(status_code=400, detail="rounds must be positive")

    # Convert dict to SessionConfig to reuse existing session-creation logic
    try:
        session_config = SessionConfig(**config_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}")

    success_count = 0
    first_view_success_count = 0
    total_latency = 0.0
    # Allow multiple view-changes within a single round before timing out,
    # preventing a systematic bias where any view-change counts as a failure.
    max_round_wait_seconds = 3.0

    # Broadcast progress roughly every 1% (≈100 updates) for convergence plots
    update_interval = max(1, rounds // 100)

    for i in range(rounds):
        # Broadcast progress (global, page-agnostic) with current round and success rate
        if i % update_interval == 0 or i == rounds - 1:
            progress_pct = int((i / rounds) * 100)
            current_round_num = i + 1
            current_rate = (success_count / current_round_num * 100) if current_round_num > 0 else 0.0
            try:
                await sio.emit(
                    "simulation_progress",
                    {
                        "progress": progress_pct,
                        "current_round": current_round_num,
                        "success_rate": current_rate,
                    },
                )
            except Exception:
                # Ignore connection errors — don't let them disrupt the simulation
                pass

        # 1. Create a fresh session for this round
        session_info = create_session(session_config, is_simulation=True)
        session_id = session_info["sessionId"]

        # 2. Ensure malicious proposer is disabled (already injected via is_simulation)
        session = get_session(session_id)
        if not session:
            continue
        session.setdefault("config", {})
        session["config"]["maliciousProposer"] = False

        # 3. Record start view and wall-clock time
        start_time = time.perf_counter()
        initial_view = session.get("current_view", 0)

        # 4. Poll for consensus result; allow view-changes within the time budget
        decided = False
        while True:
            now = time.perf_counter()
            elapsed = now - start_time
            if elapsed > max_round_wait_seconds:
                # Budget exhausted without consensus — count as failure
                break

            session = get_session(session_id)
            if not session:
                break

            consensus = session.get("consensus_result")
            if consensus:
                success_count += 1
                current_view = session.get("current_view", initial_view)
                if current_view == initial_view:
                    first_view_success_count += 1
                total_latency += elapsed
                decided = True
                break

            await asyncio.sleep(0.01)

        # Clean up the session immediately after each round to prevent memory growth
        if session_id in sessions:
            del sessions[session_id]
        if session_id in connected_nodes:
            del connected_nodes[session_id]
        if session_id in node_sockets:
            del node_sockets[session_id]

    reliability = success_count / rounds if rounds > 0 else 0.0
    first_view_reliability = first_view_success_count / rounds if rounds > 0 else 0.0
    average_latency = (total_latency / success_count) if success_count > 0 else 0.0

    return {
        "reliability": reliability,
        "first_view_reliability": first_view_reliability,
        "average_latency": average_latency,
        "rounds": rounds,
        "success_count": success_count,
        "first_view_success_count": first_view_success_count,
        "max_round_wait_seconds": max_round_wait_seconds,
    }

@app.get("/api/sessions/{session_id}")
async def get_session_info(session_id: str):
    """Return session information."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build a serialisable copy, excluding non-serialisable fields
    session_copy = {}
    for key, value in session.items():
        if key == "timeout_task":
            # Skip asyncio Task objects
            continue
        session_copy[key] = value
    
    return session_copy

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and stop all associated processes."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Mark session as stopped
    session["status"] = "stopped"

    # Clean up session data
    if session_id in sessions:
        del sessions[session_id]
    if session_id in connected_nodes:
        del connected_nodes[session_id]
    if session_id in node_sockets:
        del node_sockets[session_id]
    
    print(f"[delete_session] Session {session_id} deleted and stopped")
    
    return {"message": "Session deleted"}

@app.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """Return the current status of a session."""
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
    """Automatically assign the next available node to a new participant."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get currently connected nodes
    connected = connected_nodes.get(session_id, [])
    total_nodes = session["config"]["nodeCount"]

    # Find the first unoccupied node slot
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
    """Return the list of connected nodes for a session."""
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
    """
    Return message history for the given session, used by the frontend table and animation.

    - Without ``round``: returns a list of completed round numbers for this session.
    - With ``round``: returns the full message sequence (table_messages) and
      the frame-by-frame animation sequence (animation_sequence) for that round,
      supporting both single-layer and double-layer topologies.
    """
    from typing import List, Dict, Any

    # ---------------------------------------------------------------
    # 1. Session validation & basic config extraction
    # ---------------------------------------------------------------
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    config = session["config"]
    messages = session["messages"]
    n = config["nodeCount"]
    topology = config["topology"]
    branch_count = config.get("branchCount", 2)
    is_double_layer = branch_count > 1 and n >= branch_count * 2

    # ---------------------------------------------------------------
    # 2. No round param: return round list only (early return)
    # ---------------------------------------------------------------
    if round is None:
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

    # ---------------------------------------------------------------
    # 3. Resolve the final View for this round
    #    A round may span multiple view-changes; take the highest view
    #    (the one that reached consensus) to avoid mixing timed-out and
    #    successful messages in the animation.
    # ---------------------------------------------------------------
    target_view = round  # fallback: use round number when messages carry no view field
    all_round_msgs = []
    if messages.get("pre_prepare"):
        all_round_msgs.extend([m for m in messages["pre_prepare"] if m.get("round") == round])
    if messages.get("vote"):
        all_round_msgs.extend([m for m in messages["vote"] if m.get("round") == round])
    if messages.get("qc"):
        all_round_msgs.extend([m for m in messages["qc"] if m.get("round") == round])

    if all_round_msgs:
        views = set(m.get("view") for m in all_round_msgs if "view" in m)
        if views:
            target_view = max(views)

    historical_leader_id = target_view % n
    print(f"[get_session_history] Round {round}: showing final view {target_view}, leader ID = {historical_leader_id}")

    # ---------------------------------------------------------------
    # 4. Data containers & helper functions
    # ---------------------------------------------------------------
    table_messages: List[Dict[str, Any]] = []            # Table view: merged broadcasts, with phase
    animation_sequence: List[List[Dict[str, Any]]] = []  # Animation: split broadcasts, per frame

    def get_msgs(key, r):
        """Filter raw message list by type key and round number."""
        return [m for m in messages.get(key, []) if m.get("round") == r]

    def filter_msgs_by_view(msgs, view):
        """Keep only messages that belong to the given view."""
        return [m for m in msgs if m.get("view") == view]

    def get_node_topology(node_id):
        """Return topology-role information for a node at the historical view."""
        return get_topology_info(session, node_id, view=target_view)

    # ---------------------------------------------------------------
    # 5. Message pre-filtering: keep only messages from target_view
    # ---------------------------------------------------------------
    round_pre_prepare = filter_msgs_by_view(get_msgs("pre_prepare", round), target_view)
    round_votes       = filter_msgs_by_view(get_msgs("vote", round),        target_view)
    round_qc          = filter_msgs_by_view(get_msgs("qc", round),          target_view)

    # ---------------------------------------------------------------
    # 6. Build HotStuff 7-step animation sequence
    #    Each step corresponds to one protocol message flow.
    #    Double-layer mode splits each broadcast into two sub-frames (a/b).
    #    Steps 1 / 3 / 5 / 7 : Leader broadcast (proposal or QC)
    #    Steps 2 / 4 / 6     : Replica vote
    # ---------------------------------------------------------------

    # Step 1: Proposal (Leader -> All) [Phase: Prepare]
    step1_anim: List[Dict[str, Any]] = []
    for msg in round_pre_prepare:
        # Table entry: keep broadcast, annotate phase
        table_msg = msg.copy()
        table_msg["phase"] = "prepare"
        table_msg["type"] = "proposal"
        table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
        table_messages.append(table_msg)

        # Animation entry: split the broadcast into per-link frames
        src = msg["from"]
        value = msg.get("value")

        if is_double_layer:
            # Double-layer: Root -> Group Leaders -> Members (two sub-frames)
            # Sub-frame 1: Root -> Group Leaders
            step1a: List[Dict[str, Any]] = []
            # Sub-frame 2: Group Leaders -> Members
            step1b: List[Dict[str, Any]] = []

            for dst in range(n):
                if dst == src:
                    continue
                dst_info = get_node_topology(dst)
                if dst_info["role"] == "group_leader":
                    step1a.append({"src": src, "dst": dst, "value": value, "type": "proposal", "dst_type": "group_leaders"})
                elif dst_info["role"] == "member":
                    # Forward via this member's Group Leader
                    gl_id = dst_info["parent_id"]
                    step1b.append({"src": gl_id, "dst": dst, "value": value, "type": "proposal", "dst_type": "group_members"})

            if step1a:
                animation_sequence.append(step1a)
            if step1b:
                animation_sequence.append(step1b)
        else:
            # Single-layer: direct broadcast
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
        # Double-layer: Member -> Group Leader -> Root (two sub-frames)
        # Sub-frame 1: Member -> Group Leader
        step2a: List[Dict[str, Any]] = []
        # Sub-frame 2: Group Leader -> Root
        step2b: List[Dict[str, Any]] = []

        for vote in step2_votes:
            src_id = vote["src"]
            src_info = get_node_topology(src_id)
            dst_id = vote["dst"]

            if src_info["role"] == "member":
                # Member votes to its Group Leader
                gl_id = src_info["parent_id"]
                step2a.append({"src": src_id, "dst": gl_id, "value": vote["value"], "type": "vote", "phase": "prepare"})
            elif src_info["role"] == "group_leader" and dst_id == historical_leader_id:
                # Group Leader aggregates and votes to Root (historical leader ID)
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
        if msg.get("phase") == "prepare":  # Prepare QC triggers the Pre-Commit phase
            # Table entry
            table_msg = msg.copy()
            table_msg["phase"] = "pre-commit"
            table_msg["type"] = "qc"
            table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
            table_messages.append(table_msg)

            # Animation entry
            src = msg["from"]
            value = msg.get("qc", {}).get("value")

            if is_double_layer:
                # Double-layer: Root -> Group Leaders -> Members (two sub-frames)
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
                # Group Leader aggregates and votes to Root (historical leader ID)
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
        if msg.get("phase") == "pre-commit":  # Pre-Commit QC triggers the Commit phase
            # Table entry
            table_msg = msg.copy()
            table_msg["phase"] = "commit"
            table_msg["type"] = "qc"
            table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
            table_messages.append(table_msg)

            # Animation entry
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
                # Group Leader aggregates and votes to Root (historical leader ID)
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
        if msg.get("phase") == "commit":  # Commit QC triggers the Decide phase
            # Table entry
            table_msg = msg.copy()
            table_msg["phase"] = "decide"
            table_msg["type"] = "qc"
            table_msg["dst"] = "All" if msg.get("to") == "all" else msg.get("to")
            table_messages.append(table_msg)

            # Animation entry
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

    # ---------------------------------------------------------------
    # 7. Look up historical stats snapshot from consensus_history
    #    Prefer the snapshot to avoid mixing next-round live data into
    #    the current round's display.  Fall back to consensus_result if
    #    the history entry has not been written yet (just completed).
    # ---------------------------------------------------------------
    round_consensus = "Consensus in progress..."
    complexity_comparison = None
    historical_network_stats = {}

    found_history = False
    for history in session.get("consensus_history", []):
        if history.get("round") == round:
            found_history = True
            round_consensus = f"{history.get('status', 'Unknown')}: {history.get('description', '')}"
            if "stats" in history:
                stats_data = history["stats"]
                complexity_comparison = stats_data.get("complexity_comparison")
                historical_network_stats = stats_data.get("network_stats", {})
            break

    # Fallback: latest round just completed but not yet written to history
    if not found_history and session.get("consensus_result"):
        if session["consensus_result"].get("stats"):
            complexity_comparison = session["consensus_result"]["stats"].get("complexity_comparison")
            historical_network_stats = session["consensus_result"]["stats"].get("network_stats", {})

    # ---------------------------------------------------------------
    # 8. Assemble and return response
    # ---------------------------------------------------------------
    return {
        "round": round,
        "leaderId": historical_leader_id,          # Leader ID at the historical view
        "messages": table_messages,                # Table data (with phase, broadcasts not split)
        "animation_sequence": animation_sequence,  # Animation data (layered, per step)
        "consensus": round_consensus,
        "nodeCount": config["nodeCount"],
        "topology": config["topology"],
        "proposalValue": config["proposalValue"],
        "stats": {
            "complexity_comparison": complexity_comparison,
            # Prefer historical snapshot's network_stats
            "network_stats": historical_network_stats if historical_network_stats else session.get("network_stats", {})
        } if complexity_comparison else None
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="127.0.0.1", port=8000)
