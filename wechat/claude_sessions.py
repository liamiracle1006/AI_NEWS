# encoding:utf-8
"""Claude Code 命名工作分支的持久化层（P1.5）。

文件位置：~/.ai_news_claude_sessions.json
结构：
{
  "<user_id>": {
    "<branch_name>": {
      "session_id": "<uuid>",
      "created_at": <epoch>,
      "last_used": <epoch>,
      "task_count": <int>,
      "description": "<首次触发文本前 80 字>",
    }
  }
}

设计决策（确认过的）：
- 主键：(user_id, name) 二级索引；不同人的 "gmail" 互不冲突
- 无 TTL：永不过期，必须用户手动 '删除 X 分支'
- 命名冲突：拒绝（让用户换名或先删）
- 原子写：tmp + os.replace；进程内加锁
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Optional

_LOCK = threading.Lock()


def default_path() -> str:
    return os.path.expanduser("~/.ai_news_claude_sessions.json")


def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path: str, data: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, path)


def list_for_user(user_id: str, path: str = "") -> list[dict]:
    """返回该用户的所有命名 session（按 last_used 倒序）。"""
    p = path or default_path()
    with _LOCK:
        data = _load(p)
        branches = []
        for name, v in (data.get(user_id) or {}).items():
            branches.append({
                "name": name,
                "session_id": v.get("session_id", ""),
                "created_at": v.get("created_at", 0),
                "last_used": v.get("last_used", 0),
                "task_count": v.get("task_count", 0),
                "description": v.get("description", ""),
            })
    branches.sort(key=lambda b: b["last_used"], reverse=True)
    return branches


def get_branch(user_id: str, name: str, path: str = "") -> Optional[dict]:
    """精确取一个命名 session；不存在返回 None。"""
    p = path or default_path()
    with _LOCK:
        data = _load(p)
        b = (data.get(user_id) or {}).get(name)
        return dict(b) if b else None


def create_branch(user_id: str, name: str, description: str = "",
                  path: str = "") -> tuple[bool, str]:
    """创建一个新命名 session。返回 (True, session_id) 或 (False, error_msg)。

    命名冲突时拒绝创建。
    """
    p = path or default_path()
    with _LOCK:
        data = _load(p)
        if user_id not in data:
            data[user_id] = {}
        if name in data[user_id]:
            existing = data[user_id][name]
            ts = existing.get("last_used", 0)
            when = time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "未知时间"
            return False, f"分支 '{name}' 已存在（最后活动 {when}）"
        session_id = str(uuid.uuid4())
        now = time.time()
        data[user_id][name] = {
            "session_id": session_id,
            "created_at": now,
            "last_used": now,
            "task_count": 0,
            "description": (description or "")[:80],
        }
        _save(p, data)
        return True, session_id


def touch_branch(user_id: str, name: str, path: str = "") -> bool:
    """更新 last_used + task_count。返回是否找到。"""
    p = path or default_path()
    with _LOCK:
        data = _load(p)
        if user_id in data and name in data[user_id]:
            data[user_id][name]["last_used"] = time.time()
            data[user_id][name]["task_count"] = data[user_id][name].get("task_count", 0) + 1
            _save(p, data)
            return True
    return False


def delete_branch(user_id: str, name: str, path: str = "") -> bool:
    """删除命名 session。返回是否存在并被删。"""
    p = path or default_path()
    with _LOCK:
        data = _load(p)
        if user_id in data and name in data[user_id]:
            del data[user_id][name]
            if not data[user_id]:
                del data[user_id]
            _save(p, data)
            return True
    return False
