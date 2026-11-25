# -*- coding: utf-8 -*-
"""effluent-05 · 乙（yǐ）：对账流量累计必须剔除无许可批。

红：对账服务只有“按已存在许可号分组”的明细，没有全册流量累计与无许可孤儿批剔除口径；
无许可批 DP-E55/SM-YI-55 的流量会游离/可能被混入累计。本文件钉死：
- /api/reconcile 的 summary 累计流量只计“许可册有匹配行且未作废”的正式批；
- 无许可批进入 excluded_no_permit 清单与剔除流量，绝不进 counted_flow_m3h；
- /api/reconcile/no-permit 专给对账页同源剔除明细。

救绿服务：对账服务 reconcile_svc（不是采样许可匹配单点，也不是许可服务）。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db

MISSING_PERMIT = "DP-E55"
ORPHAN_CODE = "SM-YI-55"
ORPHAN_FLOW = 555.0


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "effluent05_yi.db")
    init_db()
    with TestClient(app) as c:
        yield c


def _h(c: TestClient) -> dict:
    tok = c.post(
        "/api/login", json={"username": "admin", "password": "admin123"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _outfall_id(c: TestClient, h: dict) -> int:
    items = c.get("/api/outfalls", headers=h).json()["items"]
    return next(o["id"] for o in items if o["outfall_code"] == "OF-E1-A")


def _insert_orphan(of_id: int, code: str = ORPHAN_CODE, flow: float = ORPHAN_FLOW) -> None:
    """直插一个无许可正式批，模拟绕过准入口的历史/孤儿行（对账必须剔除）。"""
    with connect() as conn:
        conn.execute(
            """INSERT INTO sample_batches(sample_code,outfall_id,permit_ref,metrics,
               flow_m3h,generation,status,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                code,
                of_id,
                MISSING_PERMIT,
                json.dumps({"cod": 20.0, "nh3n": 1.0, "tp": 0.1}),
                flow,
                1,
                "已裁定",
                "2026-11-25T01:00:00",
            ),
        )
        conn.commit()


def _db_sums() -> tuple[float, float]:
    with connect() as conn:
        matched = conn.execute(
            """SELECT COALESCE(SUM(s.flow_m3h),0) v FROM sample_batches s
               JOIN discharge_permits p ON p.permit_code = s.permit_ref
               WHERE s.status != '作废'"""
        ).fetchone()["v"]
        all_flow = conn.execute(
            "SELECT COALESCE(SUM(flow_m3h),0) v FROM sample_batches WHERE status!='作废'"
        ).fetchone()["v"]
    return float(matched), float(all_flow)


def test_yi_01_reconcile_summary_exists_and_excludes_orphan_flow(client):
    """失败测乙：对账累计流量不得计入无许可批 555。"""
    h = _h(client)
    of_id = _outfall_id(client, h)
    _insert_orphan(of_id)
    matched_sum, all_sum = _db_sums()
    assert all_sum - matched_sum == pytest.approx(ORPHAN_FLOW, abs=1e-6)

    r = client.get("/api/reconcile", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data, (
        "对账服务必须给出 summary 流量累计与无许可剔除口径；"
        "当前 /api/reconcile 只有按许可分组的 items，无累计/剔除"
    )
    s = data["summary"]
    counted = float(s["counted_flow_m3h"])
    assert counted == pytest.approx(matched_sum, abs=1e-6), (
        f"对账累计只应含有许可匹配批 {matched_sum}，实际计了 {counted}（仍累计无许可流量）"
    )
    assert counted == pytest.approx(all_sum - ORPHAN_FLOW, abs=1e-6)
    assert float(s["excluded_no_permit_flow_m3h"]) == pytest.approx(
        ORPHAN_FLOW, abs=1e-6
    )
    assert int(s["excluded_no_permit_count"]) >= 1
    codes = [x["sample_code"] for x in data.get("excluded_no_permit", [])]
    assert ORPHAN_CODE in codes
    # 顶层别名同源，便于对账页直接绑定
    assert float(data["total_flow_m3h"]) == pytest.approx(matched_sum, abs=1e-6)


def test_yi_02_no_permit_endpoint_lists_excluded_batches(client):
    """对账页“无许可批（已剔除累计）”同源明细接口。"""
    h = _h(client)
    of_id = _outfall_id(client, h)
    _insert_orphan(of_id, "SM-YI-56", 321.0)
    r = client.get("/api/reconcile/no-permit", headers=h)
    assert r.status_code == 200, f"缺少对账无许可剔除接口: {r.status_code} {r.text}"
    body = r.json()
    codes = [x["sample_code"] for x in body["items"]]
    assert "SM-YI-56" in codes
    assert float(body["flow_m3h_total"]) == pytest.approx(321.0, abs=1e-6)
    assert all(x["permit_ref"] == MISSING_PERMIT for x in body["items"])


def test_yi_03_unknown_permit_detail_stays_empty_book(client):
    """许可册无 DP-E55：单许可对账保持 404/空册口径，不得凭空造许可。"""
    h = _h(client)
    r = client.get(f"/api/reconcile/{MISSING_PERMIT}", headers=h)
    assert r.status_code == 404


def test_yi_04_seed_permit_reconcile_regression(client):
    """既有许可对账不回归：DP-2026-E01 仍可对账且只列本许可批。"""
    h = _h(client)
    r = client.get("/api/reconcile/DP-2026-E01", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["permit_code"] == "DP-2026-E01"
    assert all(x["sample_code"].startswith("SM-") for x in body["samples"])
