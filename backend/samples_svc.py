"""采样批次入库与超标裁定。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import SampleIn
from validators import (
    adjudicate_exceed,
    metric_summary,
    validate_flow_cap,
    validate_metrics_nonneg,
    validate_outfall_open,
    validate_plant_running,
)

router = APIRouter(tags=["samples"])


def _record_permit_block(
    conn,
    permit_ref: str,
    user: str,
    body: "SampleIn",
    block_kind: str = "无许可禁建",
    source: str = "POST /api/samples",
) -> None:
    """登记一次无许可禁建/偏航拦截，总览计数与许可页拦截痕同源此表。"""
    conn.execute(
        """INSERT INTO permit_block_log(permit_ref,source,block_kind,actor,detail,created_at)
           VALUES (?,?,?,?,?,?)""",
        (
            permit_ref,
            source,
            block_kind,
            user,
            json.dumps(
                {
                    "outfall_id": body.outfall_id,
                    "sample_code": body.sample_code,
                    "deviation_note": body.deviation_note,
                },
                ensure_ascii=False,
            ),
            now_iso(),
        ),
    )


def _next_sample_code(conn, outfall_id: int) -> str:
    outfall = conn.execute(
        "SELECT outfall_code FROM outfalls WHERE id=?", (outfall_id,)
    ).fetchone()
    prefix = outfall["outfall_code"] if outfall else f"OF-{outfall_id}"
    n = conn.execute(
        "SELECT COUNT(*) c FROM sample_batches WHERE outfall_id=?", (outfall_id,)
    ).fetchone()["c"]
    return f"SM-{prefix}-{n + 1:03d}"


@router.get("/api/samples")
def list_samples(authorization: AuthHeader = None, status: str | None = None):
    require_user(authorization)
    with connect() as conn:
        q = """SELECT s.*, o.outfall_code, p.plant_code,
                      EXISTS(SELECT 1 FROM discharge_permits dp
                             WHERE dp.permit_code=s.permit_ref) AS permit_matched
               FROM sample_batches s
               JOIN outfalls o ON o.id=s.outfall_id
               JOIN plants p ON p.id=o.plant_id"""
        if status:
            rows = conn.execute(
                q + " WHERE s.status=? ORDER BY s.id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(q + " ORDER BY s.id DESC").fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["permit_matched"] = bool(d.get("permit_matched"))
            d["metrics"] = json.loads(d["metrics"] or "{}")
            items.append(d)
        return {"items": items}


@router.get("/api/samples/{sample_id}")
def get_sample(sample_id: int, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            """SELECT s.*, o.outfall_code, o.cod_limit, o.nh3n_limit, o.tp_limit,
                      p.name plant_name
               FROM sample_batches s
               JOIN outfalls o ON o.id=s.outfall_id
               JOIN plants p ON p.id=o.plant_id
               WHERE s.id=?""",
            (sample_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "采样批次不存在")
        data = dict(row)
        data["metrics"] = json.loads(data["metrics"] or "{}")
        holds = conn.execute(
            "SELECT * FROM exceed_holds WHERE sample_id=? ORDER BY id DESC",
            (sample_id,),
        ).fetchall()
        seals = conn.execute(
            "SELECT * FROM discharge_seals WHERE sample_id=? ORDER BY id DESC",
            (sample_id,),
        ).fetchall()
        releases = conn.execute(
            "SELECT * FROM discharge_releases WHERE sample_id=? ORDER BY id DESC",
            (sample_id,),
        ).fetchall()
        return {
            "sample": data,
            "exceed_holds": [dict(h) for h in holds],
            "discharge_seals": [dict(s) for s in seals],
            "discharge_releases": [dict(r) for r in releases],
        }


@router.post("/api/samples")
def create_sample(body: SampleIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    # effluent-05：同许可号抢建必须占许可锁（跨排放口也互斥）；outfall 锁只护编号生成。
    permit_lock_key = f"permit:{body.permit_ref}"
    outfall_lock_key = f"outfall:{body.outfall_id}"
    with connect() as conn:
        # 偏航闸：任何要求“无许可先放行/影子第三路”的偏离说明，记 无许可禁建偏航 并拒写。
        if body.allow_no_permit or (body.deviation_note or "").strip():
            _record_permit_block(conn, body.permit_ref, user, body, "无许可禁建偏航")
            write_audit(
                conn,
                user,
                "sample_blocked_pianhang",
                body.permit_ref,
                {"deviation_note": body.deviation_note, "allow_no_permit": body.allow_no_permit},
            )
            conn.commit()
            raise HTTPException(
                status_code=403,
                detail=(
                    "无许可禁建偏航：DP-E55 类空匹配不开影子/第三路，"
                    "已记 无许可禁建偏航 并拒写"
                ),
                headers={"X-Effluent-Permit-Block": "pianhang"},
            )
        try:
            # 许可锁先于业务校验，保证 DP-E55 空匹配的两路并发也按同号互斥、后到留争用痕。
            require_lock(conn, permit_lock_key, user)
            require_lock(conn, outfall_lock_key, user)
            outfall = conn.execute(
                """SELECT o.*, p.status plant_status, p.design_cap_m3d
                   FROM outfalls o JOIN plants p ON p.id=o.plant_id WHERE o.id=?""",
                (body.outfall_id,),
            ).fetchone()
            if not outfall:
                raise HTTPException(404, "排放口不存在")
            validate_outfall_open(outfall["status"])
            validate_plant_running(outfall["plant_status"])
            metrics = body.metrics.model_dump()
            validate_metrics_nonneg(metrics)
            validate_flow_cap(body.flow_m3h, float(outfall["design_cap_m3d"]))
            permit = conn.execute(
                "SELECT * FROM discharge_permits WHERE permit_code=?",
                (body.permit_ref,),
            ).fetchone()
            if not permit:
                # 甲路径：许可册无匹配行 → 采样正式册零增并拒收。
                _record_permit_block(conn, body.permit_ref, user, body)
                write_audit(
                    conn,
                    user,
                    "sample_blocked_no_permit",
                    body.permit_ref,
                    {"sample_code": body.sample_code, "outfall_id": body.outfall_id},
                )
                conn.commit()
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"无许可禁建：许可册无 {body.permit_ref} 匹配行，"
                        "采样正式册零增并拒收（effluent-05 甲路径）"
                    ),
                    headers={"X-Effluent-Permit-Block": "no_permit"},
                )
            if permit["status"] != "有效":
                raise HTTPException(400, "排放许可未生效")
            exceeded, metric, measured, limit = adjudicate_exceed(
                metrics,
                {
                    "cod": outfall["cod_limit"],
                    "nh3n": outfall["nh3n_limit"],
                    "tp": outfall["tp_limit"],
                },
            )
            code = body.sample_code or _next_sample_code(conn, body.outfall_id)
            if conn.execute(
                "SELECT id FROM sample_batches WHERE sample_code=?", (code,)
            ).fetchone():
                raise HTTPException(400, "采样编号已存在")
            status = "旁路挂起" if exceeded else "已裁定"
            adjudicated = None if exceeded else now_iso()
            cur = conn.execute(
                """INSERT INTO sample_batches(sample_code,outfall_id,permit_ref,metrics,
                   flow_m3h,generation,status,adjudicated_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    code,
                    body.outfall_id,
                    body.permit_ref,
                    json.dumps(metrics, ensure_ascii=False),
                    body.flow_m3h,
                    1,
                    status,
                    adjudicated,
                    now_iso(),
                ),
            )
            sid = cur.lastrowid
            hold = None
            if exceeded:
                hold_key = f"EX-{code}-{metric}"
                conn.execute(
                    """INSERT INTO exceed_holds(sample_id,hold_key,exceed_metric,measured,
                       limit_value,status,opened_at,note)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        sid,
                        hold_key,
                        metric,
                        measured,
                        limit,
                        "开放",
                        now_iso(),
                        "入库自动挂起",
                    ),
                )
                hold = hold_key
            write_audit(
                conn,
                user,
                "sample_create",
                code,
                {
                    "status": status,
                    "metrics": metrics,
                    "summary": metric_summary(metrics),
                    "exceed": exceeded,
                    "permit_lock": permit_lock_key,
                },
            )
            conn.commit()
            return {
                "id": sid,
                "sample_code": code,
                "status": status,
                "exceed": exceeded,
                "hold_key": hold,
                "permit_lock_key": permit_lock_key,
            }
        finally:
            release(conn, permit_lock_key, user)
            release(conn, outfall_lock_key, user)
            conn.commit()
