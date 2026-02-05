from typing import Dict, List, Any, Optional
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
