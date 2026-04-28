from typing import Dict, Any, Optional


def get_quorum_threshold(session: Dict[str, Any]) -> int:
    """Return the global quorum threshold: 2f+1, where f = floor((N-1)/3)."""
    n = session["config"]["nodeCount"]
    f = (n - 1) // 3
    return 2 * f + 1


def get_local_quorum_threshold(session: Dict[str, Any], group_size: int) -> int:
    """Return the local quorum threshold for a group: 2f_local+1."""
    f_local = (group_size - 1) // 3
    return 2 * f_local + 1


def get_next_phase(phase: str) -> str:
    """Return the next HotStuff phase given the current one."""
    mapping = {
        "new-view":  "prepare",
        "prepare":   "pre-commit",
        "pre-commit": "commit",
        "commit":    "decide",
        "decide":    "decide",
    }
    return mapping.get(phase, "prepare")


def qc_extends(qc1: Optional[Dict], qc2: Optional[Dict]) -> bool:
    """
    Check whether qc1 extends qc2 (HotStuff Safety condition).

    Simplified implementation: qc1 extends qc2 iff
        qc1.view > qc2.view  AND  qc1.value == qc2.value.

    In a full block-tree implementation this would instead check the
    parent-hash chain; the value-equality check is sufficient here
    because each round proposes a single value.
    """
    if qc2 is None:
        return True   # No locked QC: any QC satisfies the condition
    if qc1 is None:
        return False

    view1  = qc1.get("view", -1)
    view2  = qc2.get("view", -1)
    value1 = qc1.get("value")
    value2 = qc2.get("value")

    return view1 > view2 and value1 == value2


def check_safe_node(
    session: Dict[str, Any],
    node_id: int,
    proposal_view: int,
    proposal_value: int,
    proposal_qc: Optional[Dict],
) -> bool:
    """
    Evaluate the HotStuff SafeNode predicate for a given proposal.

    A node accepts the proposal if either condition holds:
        1. proposal.view > lockedQC.view  (Liveness / Freshness)
        2. proposal extends lockedQC       (Safety)

    Args:
        session:        Session state dict.
        node_id:        ID of the node evaluating the proposal.
        proposal_view:  View number carried by the proposal.
        proposal_value: Proposed value.
        proposal_qc:    QC attached to the proposal (may be None).

    Returns:
        True if the node should vote for this proposal, False otherwise.
    """
    node_state = session["node_states"].get(node_id, {})
    lockedQC = node_state.get("lockedQC")

    # No locked QC yet: always accept (first proposal in this session)
    if lockedQC is None:
        print(f"Node {node_id}: SafeNode passed (no lockedQC)")
        return True

    locked_view = lockedQC.get("view", -1)

    # Condition 1: Freshness
    if proposal_view > locked_view:
        print(f"Node {node_id}: SafeNode passed (proposal_view {proposal_view} > lockedQC.view {locked_view})")
        return True

    # Condition 2: Extension
    if proposal_qc:
        if qc_extends(proposal_qc, lockedQC):
            print(f"Node {node_id}: SafeNode passed (proposal QC extends lockedQC)")
            return True
        else:
            print(f"Node {node_id}: SafeNode failed (proposal QC does not extend lockedQC)")
            return False

    # No proposal_qc provided: accept if value matches and view is not older
    locked_value = lockedQC.get("value")
    if proposal_value == locked_value and proposal_view >= locked_view:
        print(f"Node {node_id}: SafeNode passed (proposal value matches lockedQC value)")
        return True

    print(f"Node {node_id}: SafeNode failed (proposal_view {proposal_view} <= lockedQC.view {locked_view}, no extension)")
    return False


def update_node_locked_qc(session: Dict[str, Any], node_id: int, qc: Dict) -> None:
    """
    Update a node's lockedQC when a Commit-phase QC is received.

    Only updates if the incoming QC is from a strictly higher view than
    the current lockedQC.

    Args:
        session: Session state dict.
        node_id: ID of the node to update.
        qc:      Commit-phase QC to lock onto.
    """
    node_state = session["node_states"].get(node_id, {})
    current_locked = node_state.get("lockedQC")

    qc_view = qc.get("view", -1)
    if current_locked is None or qc_view > current_locked.get("view", -1):
        node_state["lockedQC"] = qc.copy()
        print(f"Node {node_id}: lockedQC updated to view {qc_view}")
    else:
        print(f"Node {node_id}: stale QC ignored (view {qc_view} <= current lockedQC.view {current_locked.get('view', -1)})")


def update_node_prepare_qc(session: Dict[str, Any], node_id: int, qc: Dict) -> None:
    """
    Update a node's prepareQC (and highQC) when any phase QC is received.

    highQC is always the highest-view prepareQC seen so far, used during
    the New-View message to help the new leader select a safe value.

    Args:
        session: Session state dict.
        node_id: ID of the node to update.
        qc:      Incoming QC (any phase).
    """
    node_state = session["node_states"].get(node_id, {})
    current_prepare = node_state.get("prepareQC")

    qc_view = qc.get("view", -1)
    if current_prepare is None or qc_view > current_prepare.get("view", -1):
        node_state["prepareQC"] = qc.copy()
        node_state["highQC"] = qc.copy()  # highQC == highest prepareQC
        print(f"Node {node_id}: prepareQC/highQC updated to view {qc_view}")


def is_honest(node_id: int, n: int, m: int, faulty_proposer: bool) -> bool:
    """
    Return True if the given node is honest under the current fault configuration.

    Args:
        node_id:         ID of the node to check.
        n:               Total number of nodes.
        m:               Number of faulty nodes.
        faulty_proposer: If True, node 0 (the initial proposer) is Byzantine.
    """
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
