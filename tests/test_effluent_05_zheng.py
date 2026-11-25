# -*- coding: utf-8 -*-
"""effluent-05 · 争（zhēng）：两路会话同许可号 DP-E55 并发抢建，须占“许可锁”。

口径：
- 建批串行键必须是 permit:{许可号}，而不是 outfall:{口ID}；同号跨口也互斥。
- 一路会话占住 permit:DP-E55 后，另一路同号建批必须 409，败方正式册零批，
  且 contention_log 留下 lock_key=permit:DP-E55 / action=争用失败 的痕。
- 并发脚本 scripts/ping_permit_lock.py 打同一个号 DP-E55。

红：当前建批只占 outfall:{id}，预先占 permit:DP-E55 根本不拦，DP-E55 仅撞许可不存在 400，
且 409 路径不争用留痕提交。救绿服务：锁服务 locks + 采样建批占锁键（许可锁分救）。
"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db
from models import SampleIn

MISSING_PERMIT = "DP-E55"
LOCK_KEY = f"permit:{MISSING_PERMIT}"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "effluent05_zheng.db")
    init_db()
    with TestClient(app) as c:
        yield c


def _token(c: TestClient, u: str, p: str) -> str:
    return c.post("/api/login", json={"username": u, "password": p}).json()["token"]


def _h(c: TestClient, u: str, p: str) -> dict:
    return {"Authorization": "Bearer " + _token(c, u, p)}


def _outfall_id(c: TestClient, h: dict) -> int:
    items = c.get("/api/outfalls", headers=h).json()["items"]
    return next(o["id"] for o in items if o["outfall_code"] == "OF-E1-A")


def _permit_batch_count(code: str | None = None) -> int:
    with connect() as conn:
        if code:
            return conn.execute(
                "SELECT COUNT(*) c FROM sample_batches WHERE sample_code=?", (code,)
            ).fetchone()["c"]
        return conn.execute(
            "SELECT COUNT(*) c FROM sample_batches WHERE permit_ref=?",
            (MISSING_PERMIT,),
        ).fetchone()["c"]


def test_zheng_01_lock_key_is_permit_scoped_not_outfall():
    """源码口径：建批占的必须是 permit: 许可锁（防止退回 outfall: 单点）。"""
    import inspect

    import samples_svc

    src = inspect.getsource(samples_svc.create_sample)
    assert 'permit_lock_key = f"permit:{body.permit_ref}"' in src, (
        "create_sample 必须以 permit_lock_key = f\"permit:{body.permit_ref}\" 作为许可锁键"
    )
    assert "require_lock(conn, permit_lock_key, user)" in src


def test_zheng_02_held_permit_lock_makes_loser_409_zero_batch_and_trace(client):
    """两路会话：writer 占 permit:DP-E55，admin 同号抢建 → 409 + 零批 + 争用痕。"""
    writer_h = _h(client, "writer", "writer123")
    admin_h = _h(client, "admin", "admin123")
    of_id = _outfall_id(client, admin_h)

    acq = client.post(
        f"/api/locks/acquire?lock_key={LOCK_KEY}", headers=writer_h
    )
    assert acq.status_code == 200, acq.text

    r = client.post(
        "/api/samples",
        headers=admin_h,
        json={
            "outfall_id": of_id,
            "permit_ref": MISSING_PERMIT,
            "sample_code": "SM-ZHENG-LOSER",
            "flow_m3h": 100.0,
            "metrics": {"cod": 20.0, "nh3n": 1.0, "tp": 0.1},
        },
    )
    assert r.status_code == 409, (
        f"后到会话应撞许可锁 409，实际 {r.status_code}: {r.text}"
    )
    # 败方零批（含 DP-E55 名下任何批）
    assert _permit_batch_count("SM-ZHENG-LOSER") == 0
    assert _permit_batch_count() == 0

    locks = client.get("/api/locks", headers=admin_h).json()
    traces = [
        x
        for x in locks["contention"]
        if x["lock_key"] == LOCK_KEY and x["actor"] == "admin"
    ]
    assert traces, "后到败方必须在 contention_log 留下 permit:DP-E55 争用失败痕"
    assert any("争用" in (x.get("action") or "") for x in traces)


def test_zheng_03_concurrent_sessions_same_permit_burst_all_lose_deterministically(client):
    """真并发：writer 占锁期间，Barrier 同时放行 4 个 admin 会话同号建批，须全 409 零批。"""
    writer_h = _h(client, "writer", "writer123")
    admin_bearer = "Bearer " + _token(client, "admin", "admin123")
    admin_h = {"Authorization": admin_bearer}
    of_id = _outfall_id(client, admin_h)
    assert client.post(f"/api/locks/acquire?lock_key={LOCK_KEY}", headers=writer_h).status_code == 200

    n = 4
    barrier = threading.Barrier(n)
    statuses: list[int] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        body = SampleIn(
            outfall_id=of_id,
            permit_ref=MISSING_PERMIT,
            sample_code=f"SM-ZHENG-C{i}",
            flow_m3h=100.0 + i,
            metrics={"cod": 20.0, "nh3n": 1.0, "tp": 0.1},
        )
        barrier.wait(timeout=10)
        try:
            # 直接打路由函数，跨线程各自开 sqlite 连接，逼出真实许可锁竞争
            from samples_svc import create_sample

            create_sample(body, authorization=admin_bearer)
            code = 200
        except HTTPException as exc:
            code = exc.status_code
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            code = 500
        with lock:
            statuses.append(code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"并发建批出现非预期异常: {errors}"
    assert statuses == [409] * n, f"占锁期间同号并发必须全部 409，实际 {statuses}"
    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM sample_batches WHERE permit_ref=?",
            (MISSING_PERMIT,),
        ).fetchone()["c"]
    assert total == 0, "并发抢建败方必须零批"


def test_zheng_04_same_holder_is_reentrant_and_still_permit_gated(client):
    """同持有人可重入许可锁；无许可时继续走甲路径 400，而不是被自己的锁 409。"""
    h = _h(client, "writer", "writer123")
    of_id = _outfall_id(client, h)
    assert client.post(f"/api/locks/acquire?lock_key={LOCK_KEY}", headers=h).status_code == 200
    r = client.post(
        "/api/samples",
        headers=h,
        json={
            "outfall_id": of_id,
            "permit_ref": MISSING_PERMIT,
            "sample_code": "SM-ZHENG-REENTRANT",
            "flow_m3h": 100.0,
            "metrics": {"cod": 20.0, "nh3n": 1.0, "tp": 0.1},
        },
    )
    assert r.status_code == 400
    assert _permit_batch_count("SM-ZHENG-REENTRANT") == 0
