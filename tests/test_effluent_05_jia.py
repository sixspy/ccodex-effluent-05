# -*- coding: utf-8 -*-
"""effluent-05 · 甲（jiǎ）：无许可禁建 —— 许可册无匹配行则采样正式册零增并拒收。

正确性口径（2026-11-25 拍板，甲路径）：
- 许可匹配与采样建批不得混用：入库口只做“许可册有无匹配行/是否有效”的准入；
  指标-帽对账归 reconcile 服务的 validate_permit_match。
- 许可册无 DP-E55 匹配行时，采样 POST 写口拒收，采样正式册 sample_batches 零增；
  种子目录里的无许可预置夹具 SM-E55 同样必须被零增拒收，不得盲插成入库假绿。

本文件先见红：无许可预置夹具当前被 seed_samples 盲插成正式批 SM-E55。
救绿服务：采样服务 samples_svc（含种子准入），同源投影到总览计数/许可页拦截痕/排放口正式批列。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app
from db import FIXTURES, connect, init_db

MISSING_PERMIT = "DP-E55"
PRESET_BATCH = "SM-E55"
OUTFALL_CODE = "OF-E1-A"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "effluent05_jia.db")
    init_db()
    with TestClient(app) as c:
        yield c


def _bearer(c: TestClient, username: str = "admin", password: str = "admin123") -> dict:
    tok = c.post(
        "/api/login", json={"username": username, "password": password}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _outfall_id(c: TestClient, h: dict, code: str = OUTFALL_CODE) -> int:
    items = c.get("/api/outfalls", headers=h).json()["items"]
    return next(o["id"] for o in items if o["outfall_code"] == code)


def _dp_e55_formal_count() -> int:
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM sample_batches WHERE permit_ref=?",
            (MISSING_PERMIT,),
        ).fetchone()["c"]


def _post_body(of_id: int, code: str, **extra) -> dict:
    body = {
        "outfall_id": of_id,
        "permit_ref": MISSING_PERMIT,
        "sample_code": code,
        "flow_m3h": 555.0,
        "metrics": {"cod": 20.0, "nh3n": 1.0, "tp": 0.1},
    }
    body.update(extra)
    return body


def test_jia_00_preset_fixture_lives_in_local_seed_dir():
    """污水夹具走本机种子目录：无许可预置夹具与 samples.json 预置批都在 fixtures/。"""
    preset = FIXTURES / "effluent_05_no_permit.json"
    samples = FIXTURES / "samples.json"
    assert preset.exists(), "缺少无许可预置夹具 fixtures/effluent_05_no_permit.json"
    meta = json.loads(preset.read_text(encoding="utf-8"))
    assert meta["missing_permit_code"] == MISSING_PERMIT
    rows = json.loads(samples.read_text(encoding="utf-8"))
    assert any(
        r["sample_code"] == PRESET_BATCH and r["permit_ref"] == MISSING_PERMIT
        for r in rows
    ), "samples.json 必须预置 DP-E55/SM-E55 无许可批以打出入库假绿"


def test_jia_01_empty_permit_match_means_zero_formal_increment(client):
    """核销戊：许可空匹配时采样正式册零增（预置夹具不得盲插成 SM-E55）。"""
    assert _dp_e55_formal_count() == 0, (
        "甲路径要求许可册无 DP-E55 匹配行时采样正式册零增；"
        f"当前正式册已有 {_dp_e55_formal_count()} 批（入库假绿 {PRESET_BATCH} 仍在）"
    )


def test_jia_02_create_key_rejected_and_zero_increment(client):
    """许可页无匹配时，采样页建批键（POST /api/samples）拒写，正式册增量为 0。"""
    h = _bearer(client)
    of_id = _outfall_id(client, h)
    before = _dp_e55_formal_count()
    r = client.post(
        "/api/samples", headers=h, json=_post_body(of_id, "SM-E55-JIA-KEY")
    )
    assert r.status_code == 400, f"无许可建批必须拒收，实际 {r.status_code}: {r.text}"
    assert "无许可禁建" in r.text or "许可不存在" in r.text
    assert r.headers.get("x-effluent-permit-block") == "no_permit"
    assert _dp_e55_formal_count() == before, "拒收后采样正式册不得有增量"
    with connect() as conn:
        hit = conn.execute(
            "SELECT id FROM sample_batches WHERE sample_code=?",
            ("SM-E55-JIA-KEY",),
        ).fetchone()
    assert hit is None, "被拒收的建批键不得留下正式批行"


def test_jia_03_dashboard_block_counter_plus_one_same_source(client):
    """总览页“无许可拦截”计数与建批拒收同源，拒收一次加一。"""
    h = _bearer(client)
    of_id = _outfall_id(client, h)
    before = client.get("/api/dashboard", headers=h).json().get("permit_blocked", 0)
    r = client.post(
        "/api/samples", headers=h, json=_post_body(of_id, "SM-E55-JIA-DASH")
    )
    assert r.status_code == 400
    dash = client.get("/api/dashboard", headers=h).json()
    assert dash.get("permit_blocked") == before + 1, (
        "总览页无许可拦截计数必须 +1，"
        f"before={before} after={dash.get('permit_blocked')}"
    )


def test_jia_04_permit_page_interception_trace_same_source(client):
    """许可页可列出同源无许可拦截痕。"""
    h = _bearer(client)
    of_id = _outfall_id(client, h)
    r = client.post(
        "/api/samples", headers=h, json=_post_body(of_id, "SM-E55-JIA-PERMIT-PAGE")
    )
    assert r.status_code == 400
    resp = client.get("/api/permits/interceptions", headers=h)
    assert resp.status_code == 200, f"许可页拦截痕接口缺失: {resp.status_code}"
    items = resp.json()["items"]
    assert any(
        x.get("permit_ref") == MISSING_PERMIT and x.get("block_kind") == "无许可禁建"
        for x in items
    ), "许可页拦截痕必须记录 DP-E55 无许可禁建"
    # 许可册本身确实没有 DP-E55（许可页空）
    permits = client.get("/api/permits", headers=h).json()["items"]
    assert all(p["permit_code"] != MISSING_PERMIT for p in permits)
    assert client.get(f"/api/permits/{MISSING_PERMIT}", headers=h).status_code == 404


def test_jia_05_outfall_formal_batch_list_excludes_no_permit(client):
    """排放口页正式批列表不含无许可号；即便历史孤儿行被直插库也必须过滤。"""
    h = _bearer(client)
    of_id = _outfall_id(client, h)
    with connect() as conn:
        conn.execute(
            """INSERT INTO sample_batches(sample_code,outfall_id,permit_ref,metrics,
               flow_m3h,generation,status,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                "SM-ORPHAN-JIA",
                of_id,
                "DP-NO-MATCH-99",
                json.dumps({"cod": 1.0}),
                123.0,
                1,
                "已裁定",
                "2026-11-25T00:00:00",
            ),
        )
        conn.commit()
    detail = client.get(f"/api/outfalls/{of_id}", headers=h).json()
    formal = detail.get("formal_samples")
    assert formal is not None, "排放口详情必须返回 formal_samples 正式批列表"
    assert all(s["permit_ref"] != "DP-NO-MATCH-99" for s in formal)
    assert "SM-ORPHAN-JIA" not in [s["sample_code"] for s in formal]

    resp = client.get(f"/api/outfalls/{of_id}/formal-samples", headers=h)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(s["permit_ref"] != "DP-NO-MATCH-99" for s in items)
    assert "SM-ORPHAN-JIA" not in [s["sample_code"] for s in items]


def test_jia_06_deviation_request_recorded_as_pianhang_and_refused(client):
    """偏航口径：要求开口子/走影子第三路的偏离说明，记“无许可禁建偏航”并拒写。"""
    h = _bearer(client)
    of_id = _outfall_id(client, h)
    r = client.post(
        "/api/samples",
        headers=h,
        json=_post_body(
            of_id,
            "SM-E55-PIANHANG",
            allow_no_permit=True,
            deviation_note="申请无许可先入影子/第三路放行",
        ),
    )
    assert r.status_code in (400, 403), "偏航放行请求必须拒写"
    resp = client.get("/api/permits/interceptions", headers=h)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(x.get("block_kind") == "无许可禁建偏航" for x in items), (
        "偏离说明必须以 无许可禁建偏航 归类留痕"
    )
