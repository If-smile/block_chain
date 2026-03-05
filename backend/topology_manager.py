from typing import Dict, Any, Optional


def get_current_leader(session: Dict[str, Any], view: Optional[int] = None) -> int:
    """返回指定视图的 Leader（HotStuff Leader Rotation: view % n）"""
    if view is None:
        view = session["current_view"]
    n = session["config"]["nodeCount"]
    return view % n


def _build_groups(n: int, branch_count: int) -> Dict[int, Dict[str, int]]:
    """
    根据节点总数 n 和分组数 branch_count 构建公平分组：
    - 前 remainder 组大小为 base_size + 1
    - 其余组大小为 base_size

    返回 node_to_group:
        { node_id: { group_id, group_leader_id, group_start, group_end, group_size } }
    """
    # 分组数不超过节点数，且至少为 1
    k = max(1, min(int(branch_count) if branch_count else 1, n))

    base_size = n // k
    remainder = n % k

    node_to_group: Dict[int, Dict[str, int]] = {}

    current = 0
    for gid in range(k):
        size = base_size + 1 if gid < remainder else base_size
        if size <= 0:
            continue
        start = current
        end = current + size
        leader_id = start
        for node_id in range(start, end):
            node_to_group[node_id] = {
                "group_id": gid,
                "group_leader_id": leader_id,
                "group_start": start,
                "group_end": end,
                "group_size": size,
            }
        current = end

    return node_to_group


def get_topology_info(
    session: Dict[str, Any],
    node_id: int,
    view: Optional[int] = None,
) -> Dict[str, Any]:
    """
    双层 HotStuff 通用拓扑引擎：返回节点的角色、上级以及组信息。

    角色定义:
    - 'root': Global Leader (动态计算: view % n)
    - 'group_leader': Group Leader (每个组的第一个节点，非 Global Leader)
    - 'member': Group Member (普通组员)

    参数:
        session: 会话数据
        node_id: 节点 ID
        view: 视图号（用于计算 Global Leader，默认使用当前视图）

    返回:
        {
            'role': 'root' | 'group_leader' | 'member',
            'parent_id': Optional[int],   # 上级节点 ID（root 的 parent_id 为 None）
            'group_id': Optional[int],    # 所属组 ID
            'group_size': Optional[int],  # 该组大小
            'group_leader_id': Optional[int],  # 该组组长 ID
        }
    """
    n = session["config"]["nodeCount"]
    branch_count = session["config"].get("branchCount", 2)

    if view is None:
        view = session.get("current_view", 0)
    global_leader_id = view % n

    # 先构建分组映射，确保任意 N/K 下所有节点都有组
    node_to_group = _build_groups(n, branch_count)

    group_info = node_to_group.get(node_id)
    # 理论上不会发生，如果发生则降级为单组
    if group_info is None:
        node_to_group = _build_groups(n, 1)
        group_info = node_to_group.get(node_id)

    group_id = group_info.get("group_id") if group_info else None
    group_leader_id = group_info.get("group_leader_id") if group_info else None
    group_size = group_info.get("group_size") if group_info else None

    # Global Leader（root）
    if node_id == global_leader_id:
        return {
            "role": "root",
            "parent_id": None,
            "group_id": group_id,
            "group_size": group_size,
            "group_leader_id": group_leader_id,
        }

    # 组长（非 root）
    if group_leader_id is not None and node_id == group_leader_id:
        return {
            "role": "group_leader",
            "parent_id": global_leader_id,
            "group_id": group_id,
            "group_size": group_size,
            "group_leader_id": group_leader_id,
        }

    # 普通组员：上级为其所在组的组长（若该组长刚好是 root，那么 parent_id 也等于 root）
    parent_id = group_leader_id
    return {
        "role": "member",
        "parent_id": parent_id,
        "group_id": group_id,
        "group_size": group_size,
        "group_leader_id": group_leader_id,
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
