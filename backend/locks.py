"""排放批争用锁。"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit

router = APIRouter(tags=["locks"])


def _log_contention(conn, lock_key: str, holder: str, detail: str) -> None:
    """落争用痕并立即提交，保证随后 409 回滚不会把痕迹带走。"""
    conn.execute(
        """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
           VALUES (?,?,?,?,?)""",
        (lock_key, holder, "争用失败", detail, now_iso()),
    )
    conn.commit()


def require_lock(conn, lock_key: str, holder: str) -> None:
    row = conn.execute(
        "SELECT holder FROM effluent_locks WHERE lock_key=?", (lock_key,)
    ).fetchone()
    if row and row["holder"] != holder:
        _log_contention(
            conn, lock_key, holder, f"持有人={row['holder']}；后到会话零批只留争用痕"
        )
        raise HTTPException(409, f"锁被占用：{lock_key} 持有人 {row['holder']}")
    if not row:
        try:
            conn.execute(
                "INSERT INTO effluent_locks(lock_key,holder,acquired_at) VALUES (?,?,?)",
                (lock_key, holder, now_iso()),
            )
            # 立即公布占锁，并发同号会话才能稳定读到持有人并留争用痕。
            conn.commit()
        except sqlite3.IntegrityError:
            # 两路会话同时 SELECT 均为空又同时 INSERT 同一 lock_key（主键相撞）：
            # 一路占锁成功，另一路按争用失败处理。
            conn.rollback()
            winner = conn.execute(
                "SELECT holder FROM effluent_locks WHERE lock_key=?", (lock_key,)
            ).fetchone()
            winner_name = winner["holder"] if winner else "unknown"
            _log_contention(
                conn, lock_key, holder, f"并发抢锁落败，持有人={winner_name}"
            )
            raise HTTPException(
                409, f"锁被并发抢占：{lock_key} 持有人 {winner_name}"
            ) from None


def release(conn, lock_key: str, holder: str) -> None:
    conn.execute(
        "DELETE FROM effluent_locks WHERE lock_key=? AND holder=?",
        (lock_key, holder),
    )


@router.get("/api/locks")
def list_locks(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        locks = [dict(r) for r in conn.execute("SELECT * FROM effluent_locks").fetchall()]
        logs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM contention_log ORDER BY id DESC LIMIT 50"
            ).fetchall()
        ]
        return {"locks": locks, "contention": logs}


@router.post("/api/locks/acquire")
def acquire(lock_key: str, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        require_lock(conn, lock_key, user)
        write_audit(conn, user, "lock_acquire", lock_key, {})
        conn.commit()
        return {"ok": True, "lock_key": lock_key, "holder": user}


@router.post("/api/locks/release")
def release_api(lock_key: str, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        release(conn, lock_key, user)
        write_audit(conn, user, "lock_release", lock_key, {})
        conn.commit()
        return {"ok": True}
