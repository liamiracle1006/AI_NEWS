# encoding:utf-8
"""路由可观测性 + 提醒事项的 SQLite 持久层（批 12.2 + 12.4）。

两张表：
- routes：每条用户消息的路由决策记录（input / decision_path / intent /
  confidence / elapsed_ms / outcome / routing_miss）
- reminders：单次定时提醒（12.4 用）

文件位置：~/.ai_news_routing.db（per-user 共用，单文件）

设计：
- 异步友好：所有写操作单独事务，不阻塞 dispatcher 主路径
- 进程内加锁（避免 SQLite 'database is locked'）
- 失败永远不抛——routing 日志挂了不能影响 bot
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


_LOCK = threading.Lock()
_DB_PATH: Optional[str] = None  # 懒初始化


def default_path() -> str:
    return os.path.expanduser("~/.ai_news_routing.db")


def _conn(path: Optional[str] = None) -> sqlite3.Connection:
    p = path or _DB_PATH or default_path()
    c = sqlite3.connect(p, timeout=5.0)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            user_id TEXT NOT NULL,
            msg_text TEXT NOT NULL,
            decision_path TEXT NOT NULL,
            intent TEXT,
            confidence INTEGER,
            model_used TEXT,
            elapsed_ms INTEGER,
            outcome TEXT,
            routing_miss INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_routes_user ON routes(user_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_routes_miss ON routes(routing_miss) WHERE routing_miss=1;

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            ts_due REAL NOT NULL,
            message TEXT NOT NULL,
            fired INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(fired, ts_due);

        -- P12.7 · DM Pairing：陌生人发 "/pair <码>" → 管理员批准 → 进入白名单
        CREATE TABLE IF NOT EXISTS pairings (
            user_id TEXT PRIMARY KEY,
            pair_code TEXT NOT NULL,
            status TEXT NOT NULL,  -- 'awaiting_code' | 'awaiting_admin' | 'approved' | 'rejected'
            created_at REAL NOT NULL,
            approved_at REAL
        );
    """)


def init(path: Optional[str] = None):
    """启动时调一次。重复调安全（CREATE IF NOT EXISTS）。"""
    global _DB_PATH
    _DB_PATH = path or default_path()
    try:
        with _LOCK:
            with _conn(_DB_PATH) as c:
                _ensure_schema(c)
        logger.info(f"[routing_log] initialized at {_DB_PATH}")
    except Exception as e:
        logger.warning(f"[routing_log] init failed: {e}")


# ── routes 表 ─────────────────────────────────────────────────────────────


def log_route(
    user_id: str,
    msg_text: str,
    decision_path: str,
    *,
    intent: Optional[str] = None,
    confidence: Optional[int] = None,
    model_used: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
    outcome: Optional[str] = None,
) -> Optional[int]:
    """记一条路由决策。返回 route_id 供后续 mark_miss 用。失败返回 None。"""
    try:
        with _LOCK:
            with _conn() as c:
                cursor = c.execute(
                    """INSERT INTO routes
                       (ts, user_id, msg_text, decision_path, intent,
                        confidence, model_used, elapsed_ms, outcome)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (time.time(), user_id, msg_text[:500], decision_path,
                     intent, confidence, model_used, elapsed_ms, outcome),
                )
                return cursor.lastrowid
    except Exception as e:
        logger.warning(f"[routing_log] log_route failed: {e}")
        return None


def mark_miss(route_id: int) -> bool:
    """回填 routing_miss=1（用户表明上一条路由错了）。"""
    if route_id is None or route_id <= 0:
        return False
    try:
        with _LOCK:
            with _conn() as c:
                c.execute("UPDATE routes SET routing_miss=1 WHERE id=?", (route_id,))
        return True
    except Exception as e:
        logger.warning(f"[routing_log] mark_miss failed: {e}")
        return False


def get_last_route_for_user(user_id: str) -> Optional[dict]:
    """取该用户最新一条 route 记录（用于 mark_miss 回填）。"""
    try:
        with _LOCK:
            with _conn() as c:
                row = c.execute(
                    "SELECT id, msg_text, decision_path, intent FROM routes "
                    "WHERE user_id=? ORDER BY ts DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
                if row:
                    return {"id": row[0], "msg_text": row[1],
                            "decision_path": row[2], "intent": row[3]}
                return None
    except Exception as e:
        logger.warning(f"[routing_log] get_last_route failed: {e}")
        return None


def recent_routes(user_id: str, limit: int = 20) -> list[dict]:
    """该用户最近 N 条路由记录（用于"路由日志"管理命令）。"""
    try:
        with _LOCK:
            with _conn() as c:
                rows = c.execute(
                    """SELECT id, ts, msg_text, decision_path, intent,
                              confidence, routing_miss
                       FROM routes WHERE user_id=?
                       ORDER BY ts DESC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
                return [{
                    "id": r[0], "ts": r[1], "msg_text": r[2],
                    "decision_path": r[3], "intent": r[4],
                    "confidence": r[5], "routing_miss": bool(r[6]),
                } for r in rows]
    except Exception as e:
        logger.warning(f"[routing_log] recent_routes failed: {e}")
        return []


def miss_rate(user_id: str, recent_n: int = 100) -> float:
    """最近 N 条路由的 miss 率（0-1）。少于 5 条时返回 0。"""
    try:
        with _LOCK:
            with _conn() as c:
                rows = c.execute(
                    "SELECT routing_miss FROM routes WHERE user_id=? "
                    "ORDER BY ts DESC LIMIT ?",
                    (user_id, recent_n),
                ).fetchall()
                if len(rows) < 5:
                    return 0.0
                return sum(1 for r in rows if r[0]) / len(rows)
    except Exception:
        return 0.0


# ── reminders 表（P12.4 提醒用，提前建好） ────────────────────────────────


def add_reminder(user_id: str, ts_due: float, message: str) -> Optional[int]:
    """添加单次定时提醒，返回 reminder_id。"""
    try:
        with _LOCK:
            with _conn() as c:
                cursor = c.execute(
                    "INSERT INTO reminders (user_id, ts_due, message, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, ts_due, message[:500], time.time()),
                )
                return cursor.lastrowid
    except Exception as e:
        logger.warning(f"[routing_log] add_reminder failed: {e}")
        return None


def due_reminders(now: Optional[float] = None) -> list[dict]:
    """到期未触发的提醒。"""
    if now is None:
        now = time.time()
    try:
        with _LOCK:
            with _conn() as c:
                rows = c.execute(
                    "SELECT id, user_id, ts_due, message FROM reminders "
                    "WHERE fired=0 AND ts_due<=?",
                    (now,),
                ).fetchall()
                return [{"id": r[0], "user_id": r[1],
                         "ts_due": r[2], "message": r[3]} for r in rows]
    except Exception:
        return []


def mark_reminder_fired(reminder_id: int) -> bool:
    try:
        with _LOCK:
            with _conn() as c:
                c.execute("UPDATE reminders SET fired=1 WHERE id=?", (reminder_id,))
        return True
    except Exception:
        return False


def list_pending_reminders(user_id: str) -> list[dict]:
    try:
        with _LOCK:
            with _conn() as c:
                rows = c.execute(
                    "SELECT id, ts_due, message FROM reminders "
                    "WHERE user_id=? AND fired=0 ORDER BY ts_due ASC",
                    (user_id,),
                ).fetchall()
                return [{"id": r[0], "ts_due": r[1], "message": r[2]}
                        for r in rows]
    except Exception:
        return []


def cancel_reminder(reminder_id: int) -> bool:
    try:
        with _LOCK:
            with _conn() as c:
                cursor = c.execute(
                    "UPDATE reminders SET fired=1 WHERE id=? AND fired=0",
                    (reminder_id,),
                )
                return cursor.rowcount > 0
    except Exception:
        return False


# ── pairings 表（P12.7 DM Pairing）─────────────────────────────────────────


def get_pairing(user_id: str) -> Optional[dict]:
    try:
        with _LOCK:
            with _conn() as c:
                row = c.execute(
                    "SELECT user_id, pair_code, status, created_at, approved_at "
                    "FROM pairings WHERE user_id=?",
                    (user_id,),
                ).fetchone()
                if not row:
                    return None
                return {"user_id": row[0], "pair_code": row[1],
                        "status": row[2], "created_at": row[3],
                        "approved_at": row[4]}
    except Exception:
        return None


def upsert_pairing(user_id: str, pair_code: str, status: str) -> bool:
    try:
        with _LOCK:
            with _conn() as c:
                c.execute(
                    """INSERT INTO pairings (user_id, pair_code, status, created_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id) DO UPDATE SET
                         pair_code=excluded.pair_code,
                         status=excluded.status""",
                    (user_id, pair_code, status, time.time()),
                )
        return True
    except Exception as e:
        logger.warning(f"[routing_log] upsert_pairing failed: {e}")
        return False


def approve_pairing(user_id: str) -> bool:
    try:
        with _LOCK:
            with _conn() as c:
                cursor = c.execute(
                    "UPDATE pairings SET status='approved', approved_at=? "
                    "WHERE user_id=? AND status IN ('awaiting_code', 'awaiting_admin')",
                    (time.time(), user_id),
                )
                return cursor.rowcount > 0
    except Exception:
        return False


def list_pending_pairings() -> list[dict]:
    """列出等管理员批准的配对申请。"""
    try:
        with _LOCK:
            with _conn() as c:
                rows = c.execute(
                    "SELECT user_id, pair_code, created_at FROM pairings "
                    "WHERE status='awaiting_admin' ORDER BY created_at ASC"
                ).fetchall()
                return [{"user_id": r[0], "pair_code": r[1],
                         "created_at": r[2]} for r in rows]
    except Exception:
        return []


def is_paired(user_id: str) -> bool:
    p = get_pairing(user_id)
    return p is not None and p["status"] == "approved"
