import os
import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List


DB_PATH = os.path.join(os.path.dirname(__file__), "blockchain_sim.db")


def _get_connection() -> sqlite3.Connection:
    """获取 SQLite 连接（开启外键约束）"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """初始化数据库和表结构"""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        # 会话表：存储当前会话的完整状态快照
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                config     TEXT NOT NULL,  -- 会话配置（JSON）
                state      TEXT NOT NULL,  -- 会话完整状态（JSON，已过滤不可序列化字段）
                updated_at TEXT NOT NULL
            );
            """
        )

        # 历史表：存储每一轮共识的历史记录（包含统计快照）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                round      INTEGER NOT NULL,
                data       TEXT NOT NULL,  -- 单条历史记录完整 JSON
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
            """
        )

        conn.commit()
    finally:
        conn.close()


def _sanitize_session_data(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    过滤掉不可序列化的字段，只保留纯数据结构以便写入 SQLite/JSON。

    典型需要移除的字段：
    - asyncio 任务对象：timeout_task
    - 未来如有锁对象等，也会被自动过滤掉（json.dumps 测试失败即丢弃）
    """
    if session is None:
        return {}

    # 先做浅拷贝，避免修改原始对象
    data = dict(session)

    # 显式移除已知不可序列化字段
    data.pop("timeout_task", None)

    sanitized: Dict[str, Any] = {}
    for key, value in data.items():
        try:
            # 尝试序列化，如果失败直接跳过该字段
            json.dumps(value)
        except TypeError as e:
            print(f"[CRITICAL WARNING] 字段 {key} 序列化失败，数据已丢弃: {e}")
            continue
        else:
            sanitized[key] = value

    return sanitized


def upsert_session(session_id: str, session_data: Dict[str, Any]) -> None:
    """
    插入或更新会话状态快照。

    - session_data 将通过 _sanitize_session_data 过滤不可序列化字段
    - config 字段单独存储，便于快速查看
    """
    if not session_id or not isinstance(session_data, dict):
        return

    sanitized = _sanitize_session_data(session_data)
    config = sanitized.get("config", {})

    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sessions (session_id, config, state, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                config = excluded.config,
                state = excluded.state,
                updated_at = excluded.updated_at;
            """,
            (
                session_id,
                json.dumps(config, ensure_ascii=False),
                json.dumps(sanitized, ensure_ascii=False),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_all_sessions() -> Dict[str, Dict[str, Any]]:
    """
    加载所有持久化会话，返回 {session_id: state_dict}。
    """
    conn = _get_connection()
    sessions: Dict[str, Dict[str, Any]] = {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT session_id, state FROM sessions;")
        for session_id, state_json in cur.fetchall():
            try:
                state = json.loads(state_json)
                if isinstance(state, dict):
                    sessions[session_id] = state
            except json.JSONDecodeError:
                print(f"[CRITICAL WARNING] 会话 {session_id} 状态加载失败 (JSON Decode Error)，已跳过")
                continue
    finally:
        conn.close()

    return sessions


def append_history(session_id: str, history_item: Dict[str, Any]) -> None:
    """
    追加一条共识历史记录。
    history_item 通常是 finalize_consensus 中写入 consensus_history 的那条字典。
    """
    if not session_id or not isinstance(history_item, dict):
        return

    # 确保 round 可用（没有则退化为 0）
    round_value = history_item.get("round")
    try:
        round_int = int(round_value) if round_value is not None else 0
    except (TypeError, ValueError):
        round_int = 0

    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO history (session_id, round, data, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (
                session_id,
                round_int,
                json.dumps(history_item, ensure_ascii=False),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_history(session_id: str) -> List[Dict[str, Any]]:
    """
    加载指定会话的全部历史记录（按插入顺序）。
    """
    if not session_id:
        return []

    conn = _get_connection()
    items: List[Dict[str, Any]] = []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT data FROM history WHERE session_id = ? ORDER BY id ASC;",
            (session_id,),
        )
        for (data_json,) in cur.fetchall():
            try:
                item = json.loads(data_json)
                if isinstance(item, dict):
                    items.append(item)
            except json.JSONDecodeError:
                print(f"[CRITICAL WARNING] 历史记录解析失败 (JSON Decode Error)，已跳过")
                continue
    finally:
        conn.close()

    return items

