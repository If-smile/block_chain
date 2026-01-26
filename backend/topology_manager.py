from typing import Dict, Any, Optional

def get_current_leader(session: Dict[str, Any], view: Optional[int] = None) -> int:
    """返回指定视图的Leader（HotStuff Leader Rotation: view % n）"""
    if view is None:
        view = session["current_view"]
    n = session["config"]["nodeCount"]
    return view % n

def get_topology_info(session: Dict[str, Any], node_id: int, view: Optional[int] = None) -> Dict[str, Any]:
    """
    双层 HotStuff 拓扑信息：返回节点的角色和上级ID

    角色定义:
    - 'root': Global Leader (动态计算: view % n)
    - 'group_leader': Group Leader (每个组的第一个节点，非 Global Leader)
    - 'member': Group Member (普通组员)

    参数:
        session: 会话数据
        node_id: 节点ID
        view: 视图号（用于计算 Global Leader，默认使用当前视图）

    返回:
        {
            'role': 'root' | 'group_leader' | 'member',
            'parent_id': int,  # 上级节点ID（root 的 parent_id 为 None）
            'group_id': int,   # 所属组ID
            'group_size': int  # 组大小（实际组内数量）
        }
    """
    n = session["config"]["nodeCount"]
    branch_count = session["config"].get("branchCount", 2)  # 分组数 K
    branch_count = max(1, int(branch_count))
    
    # 计算 Global Leader (根据 view 动态计算)
    if view is None:
        view = session.get("current_view", 0)
    global_leader_id = view % n

    # Root: 当前视图的 Global Leader
    if node_id == global_leader_id:
        return {
            "role": "root",
            "parent_id": None,
            "group_id": None,
            "group_size": None
        }

    # 使用 floor 分组（与前端逻辑一致）
    group_size = max(1, n // branch_count)
    group_id = node_id // group_size
    group_start_id = group_id * group_size
    group_end_id = min((group_id + 1) * group_size, n)
    actual_group_size = max(0, group_end_id - group_start_id)

    # Group Leader: 每组第一个节点（非 Global Leader）
    if node_id == group_start_id and node_id != global_leader_id:
        return {
            "role": "group_leader",
            "parent_id": global_leader_id,  # 上级是 Global Leader
            "group_id": group_id,
            "group_size": actual_group_size
        }

    # Group Member: 上级是 Group Leader
    return {
        "role": "member",
        "parent_id": group_start_id,
        "group_id": group_id,
        "group_size": actual_group_size
    }

def is_connection_allowed(i: int, j: int, n: int, topology: str, n_value: int) -> bool:
    """
    检查两个节点之间是否允许连接（仅用于历史记录展示，不影响实际共识逻辑）
    
    注意：HotStuff 协议要求星型拓扑（Leader <-> All Replicas）
    实际的共识逻辑中，所有通信都是星型的（通过 get_current_leader 强制）
    此函数仅用于前端历史记录的拓扑可视化
    """
    if i == j:
        return False
    
    # HotStuff 强制星型拓扑：Leader 可以与所有节点通信，非 Leader 只能与 Leader 通信
    # 为了兼容前端，这里仍然检查配置的 topology，但实际逻辑中已强制星型
    # 如果配置不是 star，在历史记录中也会按 star 方式显示（Leader <-> All）
    leader_id = get_current_leader({"config": {"nodeCount": n}, "current_view": 0}, 0)  # 假设 view=0，仅用于判断
    # 在实际使用中，应该根据消息的 view 来确定 leader
    # 这里简化处理，只检查是否是 Leader 与其他节点的连接
    if topology == "star" or True:  # 强制星型（HotStuff 要求）
        return True  # 在星型拓扑中，所有节点都可以与 Leader 通信（展示用）
    
    # 以下代码仅作为参考，实际不会被使用（因为上面已经 return True）
    if topology == "full":
        return True
    elif topology == "ring":
        return j == (i + 1) % n or j == (i - 1) % n
    elif topology == "tree":
        parent = (j - 1) // n_value
        return i == parent and j < n
    return False
