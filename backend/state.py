from typing import Dict, List, Any, Optional
import random
import socketio

# 创建Socket.IO服务器
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*"
)

# 全局状态管理
sessions: Dict[str, Dict[str, Any]] = {}
connected_nodes: Dict[str, List[int]] = {}
node_sockets: Dict[str, Dict[int, str]] = {}

# 会话管理
def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    return sessions.get(session_id)


def should_deliver_message(session_id: str) -> bool:
    """根据消息传达概率决定是否发送消息"""
    session = get_session(session_id)
    if not session:
        return True
    delivery_rate = session["config"].get("messageDeliveryRate", 100)
    if delivery_rate >= 100:
        return True
    return random.random() * 100 < delivery_rate


def count_message_sent(session_id: str, is_broadcast: bool = True, target_count: Optional[int] = None) -> None:
    """统计发送的消息数量（用于 Shadow 与全链路统计）"""
    session = get_session(session_id)
    if not session:
        return
    if "network_stats" not in session:
        session["network_stats"] = {
            "total_messages_sent": 0,
            "phases_count": 0
        }
    if is_broadcast:
        n = session["config"]["nodeCount"]
        message_count = max((n - 1) if target_count is None else int(target_count), 0)
    else:
        message_count = 1
    session["network_stats"]["total_messages_sent"] += message_count
