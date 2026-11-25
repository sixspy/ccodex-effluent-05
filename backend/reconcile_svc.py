"""排放许可与采样对账证明。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user
from validators import validate_permit_match

router = APIRouter(tags=["reconcile"])


def _no_permit_batches(conn) -> list[dict]:
    """许可册无匹配行的正式批（无许可批）。对账流量累计必须剔除它们。"""
    rows = conn.execute(
        """SELECT s.sample_code, s.permit_ref, s.flow_m3h, s.status, s.generation,
                  s.created_at, o.outfall_code
           FROM sample_batches s
           LEFT JOIN discharge_permits p ON p.permit_code = s.permit_ref
           LEFT JOIN outfalls o ON o.id = s.outfall_id
           WHERE p.id IS NULL AND s.status != '作废'
           ORDER BY s.id""",
    ).fetchall()
    return [dict(r) for r in rows]


def _flow_summary(conn) -> dict:
    no_permit = _no_permit_batches(conn)
    excluded_flow = sum(float(x["flow_m3h"] or 0.0) for x in no_permit)
    counted = conn.execute(
        """SELECT COALESCE(SUM(s.flow_m3h),0) v, COUNT(*) c
           FROM sample_batches s
           JOIN discharge_permits p ON p.permit_code = s.permit_ref
           WHERE s.status != '作废'"""
    ).fetchone()
    formal = conn.execute(
        "SELECT COUNT(*) c FROM sample_batches WHERE status != '作废'"
    ).fetchone()["c"]
    counted_flow = float(counted["v"])
    return {
        "formal_batch_count": formal,
        "counted_batch_count": int(counted["c"]),
        "excluded_no_permit_count": len(no_permit),
        "counted_flow_m3h": counted_flow,
        "total_flow_m3h": counted_flow,
        "included_flow_m3h": counted_flow,
        "excluded_no_permit_flow_m3h": excluded_flow,
        "no_permit_flow_m3h": excluded_flow,
        "flow_unit": "m3/h",
        "rule": "对账流量累计只计许可册有匹配行的正式批；无许可批剔除并列入 excluded_no_permit",
    }


@router.get("/api/reconcile")
def reconcile_all(authorization: AuthHeader = None):
    require_user(authorization)
    from db import connect

    with connect() as conn:
        rows = conn.execute(
            "SELECT permit_code FROM discharge_permits ORDER BY permit_code"
        ).fetchall()
        items = [_reconcile_permit(conn, r["permit_code"]) for r in rows]
        unmatched = _no_permit_batches(conn)
        summary = _flow_summary(conn)
        return {
            "items": items,
            "summary": summary,
            "unmatched": unmatched,
            "excluded_no_permit": unmatched,
            # 顶层别名，便于对账页直接绑定“累计（已剔除无许可）流量”
            "total_flow_m3h": summary["counted_flow_m3h"],
            "counted_flow_m3h": summary["counted_flow_m3h"],
            "excluded_no_permit_flow_m3h": summary["excluded_no_permit_flow_m3h"],
        }


@router.get("/api/reconcile/no-permit")
def reconcile_no_permit(authorization: AuthHeader = None):
    """无许可批剔除明细（必须定义在 /api/reconcile/{permit_code} 之前）。"""
    require_user(authorization)
    from db import connect

    with connect() as conn:
        items = _no_permit_batches(conn)
        total = sum(float(x["flow_m3h"] or 0.0) for x in items)
        return {
            "items": items,
            "count": len(items),
            "flow_m3h_total": total,
            "rule": "这些批许可册无匹配行，已从对账流量累计剔除（effluent-05 乙）",
        }


@router.get("/api/reconcile/{permit_code}")
def reconcile_one(permit_code: str, authorization: AuthHeader = None):
    require_user(authorization)
    from db import connect

    with connect() as conn:
        if not conn.execute(
            "SELECT id FROM discharge_permits WHERE permit_code=?", (permit_code,)
        ).fetchone():
            raise HTTPException(404, "许可不存在")
        return _reconcile_permit(conn, permit_code)


def _reconcile_permit(conn, permit_code: str) -> dict:
    permit = conn.execute(
        "SELECT * FROM discharge_permits WHERE permit_code=?", (permit_code,)
    ).fetchone()
    samples = conn.execute(
        """SELECT sample_code, flow_m3h, metrics, status, generation FROM sample_batches
           WHERE permit_ref=? AND status NOT IN ('作废')""",
        (permit_code,),
    ).fetchall()
    if not samples:
        return {
            "permit_code": permit_code,
            "balanced": False,
            "reason": "无采样批次",
            "samples": [],
        }
    caps = {
        "cod": permit["cod_cap"],
        "nh3n": permit["nh3n_cap"],
        "tp": permit["tp_cap"],
    }
    details = []
    all_ok = True
    for s in samples:
        metrics = json.loads(s["metrics"] or "{}")
        ok = validate_permit_match(
            caps, metrics, float(s["flow_m3h"]), float(permit["quota_m3d"])
        )
        if not ok:
            all_ok = False
        details.append(
            {
                "sample_code": s["sample_code"],
                "status": s["status"],
                "generation": s["generation"],
                "metrics": metrics,
                "flow_m3h": s["flow_m3h"],
                "matched": ok,
            }
        )
    seal_rows = conn.execute(
        """SELECT d.seal_ref, d.sample_generation, s.sample_code
           FROM discharge_seals d JOIN sample_batches s ON s.id=d.sample_id
           WHERE s.permit_ref=?""",
        (permit_code,),
    ).fetchall()
    return {
        "permit_code": permit_code,
        "quota_m3d": permit["quota_m3d"],
        "caps": caps,
        "balanced": all_ok,
        "proof_ready": all_ok and len(seal_rows) >= 1,
        "seal_count": len(seal_rows),
        "sample_count": len(details),
        "flow_total_m3h": sum(float(d["flow_m3h"] or 0.0) for d in details),
        "samples": details,
        "seals": [dict(x) for x in seal_rows],
    }


@router.get("/api/proof/sample/{sample_code}")
def proof_sample(sample_code: str, authorization: AuthHeader = None):
    require_user(authorization)
    from db import connect

    with connect() as conn:
        sample = conn.execute(
            "SELECT * FROM sample_batches WHERE sample_code=?", (sample_code,)
        ).fetchone()
        if not sample:
            raise HTTPException(404, "采样不存在")
        holds = conn.execute(
            "SELECT * FROM exceed_holds WHERE sample_id=?", (sample["id"],)
        ).fetchall()
        releases = conn.execute(
            "SELECT * FROM discharge_releases WHERE sample_id=?", (sample["id"],)
        ).fetchall()
        seals = conn.execute(
            "SELECT * FROM discharge_seals WHERE sample_id=?", (sample["id"],)
        ).fetchall()
        open_holds = [h for h in holds if h["status"] == "开放"]
        closed = [h for h in holds if h["status"] == "已关闭"]
        return {
            "sample_code": sample_code,
            "status": sample["status"],
            "generation": sample["generation"],
            "released": any(r["status"] == "已准排" for r in releases),
            "sealed": any(s["status"] == "已封批" for s in seals),
            "exceed_closed": len(open_holds) == 0 and (len(closed) > 0 or sample["status"] != "旁路挂起"),
            "holds": [dict(h) for h in holds],
            "releases": [dict(r) for r in releases],
            "seals": [dict(s) for s in seals],
        }
