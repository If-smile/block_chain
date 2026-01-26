from typing import Dict, Any, Optional

def get_quorum_threshold(session: Dict[str, Any]) -> int:
    """HotStuff 需要 2f+1 票（全局阈值）"""
    n = session["config"]["nodeCount"]
    f = (n - 1) // 3
    return 2 * f + 1

def get_local_quorum_threshold(session: Dict[str, Any], group_size: int) -> int:
    """双层 HotStuff 组内阈值：需要 2f_local + 1 票"""
    f_local = (group_size - 1) // 3
    return 2 * f_local + 1

def get_next_phase(phase: str) -> str:
    """HotStuff 阶段流转"""
    mapping = {
        "new-view": "prepare",
        "prepare": "pre-commit",
        "pre-commit": "commit",
        "commit": "decide",
        "decide": "decide"
    }
    return mapping.get(phase, "prepare")

def qc_extends(qc1: Optional[Dict], qc2: Optional[Dict]) -> bool:
    """检查 qc1 是否扩展自 qc2（HotStuff 的 Safety 条件：extends 关系）"""
    if qc2 is None:
        return True  # 如果 lockedQC 为空，任何 QC 都满足条件
    if qc1 is None:
        return False
    
    # 简化实现：检查 view 和 value 的继承关系
    # 在实际 HotStuff 中，这需要检查区块链的父节点关系
    # 这里我们简化为：如果 qc1.view > qc2.view 且 value 相同，则视为扩展
    view1 = qc1.get("view", -1)
    view2 = qc2.get("view", -1)
    value1 = qc1.get("value")
    value2 = qc2.get("value")
    
    # 如果 qc1 的 view 更高且 value 相同，则视为扩展关系
    return view1 > view2 and value1 == value2

def check_safe_node(session: Dict[str, Any], node_id: int, proposal_view: int, proposal_value: int, proposal_qc: Optional[Dict]) -> bool:
    """
    HotStuff SafeNode 谓词检查（Safety 的核心机制）
    
    条件：msg.view > lockedQC.view OR msg.extends(lockedQC)
    
    参数:
        session: 会话数据
        node_id: 节点ID
        proposal_view: 提案的视图号
        proposal_value: 提案的值
        proposal_qc: 提案携带的 QC（可选）
    
    返回:
        bool: 如果通过 SafeNode 检查返回 True，否则返回 False
    """
    node_state = session["node_states"].get(node_id, {})
    lockedQC = node_state.get("lockedQC")
    
    # 条件1: proposal_view > lockedQC.view (Liveness/Freshness)
    if lockedQC is None:
        # 如果没有锁定QC，允许投票（首次提案）
        print(f"节点 {node_id}: SafeNode 检查通过（无 lockedQC）")
        return True
    
    locked_view = lockedQC.get("view", -1)
    if proposal_view > locked_view:
        print(f"节点 {node_id}: SafeNode 检查通过（proposal_view {proposal_view} > lockedQC.view {locked_view}）")
        return True
    
    # 条件2: proposal.extends(lockedQC) (Safety)
    if proposal_qc:
        if qc_extends(proposal_qc, lockedQC):
            print(f"节点 {node_id}: SafeNode 检查通过（proposal QC 扩展自 lockedQC）")
            return True
        else:
            print(f"节点 {node_id}: SafeNode 检查失败（proposal QC 不扩展自 lockedQC）")
            return False
    
    # 如果 proposal_qc 为空但 proposal_value 与 lockedQC.value 相同，也视为扩展
    locked_value = lockedQC.get("value")
    if proposal_value == locked_value and proposal_view >= locked_view:
        print(f"节点 {node_id}: SafeNode 检查通过（proposal value 与 lockedQC value 相同）")
        return True
    
    # 不满足任何条件，拒绝提案
    print(f"节点 {node_id}: SafeNode 检查失败（proposal_view {proposal_view} <= lockedQC.view {locked_view} 且不扩展）")
    return False

def update_node_locked_qc(session: Dict[str, Any], node_id: int, qc: Dict):
    """
    更新节点的 lockedQC（在收到 CommitQC 时调用）
    
    参数:
        session: 会话数据
        node_id: 节点ID
        qc: 新的 QC（必须是 Commit 阶段的 QC）
    """
    node_state = session["node_states"].get(node_id, {})
    current_locked = node_state.get("lockedQC")
    
    qc_view = qc.get("view", -1)
    if current_locked is None or qc_view > current_locked.get("view", -1):
        node_state["lockedQC"] = qc.copy()
        print(f"节点 {node_id}: 更新 lockedQC 到 view {qc_view}")
    else:
        print(f"节点 {node_id}: 忽略旧的 QC（view {qc_view} <= current lockedQC.view {current_locked.get('view', -1)}）")

def update_node_prepare_qc(session: Dict[str, Any], node_id: int, qc: Dict):
    """
    更新节点的 prepareQC（在收到任何阶段的 QC 时调用，用于 New-View 选择 HighQC）
    
    参数:
        session: 会话数据
        node_id: 节点ID
        qc: 新的 QC
    """
    node_state = session["node_states"].get(node_id, {})
    current_prepare = node_state.get("prepareQC")
    
    qc_view = qc.get("view", -1)
    if current_prepare is None or qc_view > current_prepare.get("view", -1):
        node_state["prepareQC"] = qc.copy()
        node_state["highQC"] = qc.copy()  # HighQC 就是最高的 prepareQC
        print(f"节点 {node_id}: 更新 prepareQC/highQC 到 view {qc_view}")

def is_honest(node_id: int, n: int, m: int, faulty_proposer: bool) -> bool:
    """判断节点是否为诚实节点"""
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
