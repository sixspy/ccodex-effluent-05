#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""effluent-05 并发脚本 ping_permit_lock —— 两路/多路会话同许可号 DP-E55 抢建批。

打同一个号：permit:DP-E55。

验证：
1. 一会话占住许可锁后，Barrier 同时放行的并发同号建批请求必须全部 409，
   败方正式册零批，且 GET /api/locks 的 contention 留 permit:DP-E55 争用痕。
2. 不预占锁的两路真并发裸抢，安全不变量同样成立：无 2xx、DP-E55 零正式批。

用法：
    python scripts/ping_permit_lock.py [base_url]
    EFFLUENT_BASE_URL=http://127.0.0.1:8000 python scripts/ping_permit_lock.py

仅用标准库，可直接用系统 python3 打正在运行的 uvicorn / docker 映射端口。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PERMIT = "DP-E55"
LOCK_KEY = f"permit:{PERMIT}"
OUTFALL_CODE = "OF-E1-A"


def base_url() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1].rstrip("/")
    return os.environ.get("EFFLUENT_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def call(method: str, path: str, token: str | None = None, payload: dict | None = None):
    url = base_url() + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        return exc.code, body


def login(user: str, pw: str) -> str:
    status, body = call("POST", "/api/login", payload={"username": user, "password": pw})
    assert status == 200, f"login {user} failed: {status} {body}"
    return body["token"]


def outfall_id(token: str) -> int:
    status, body = call("GET", "/api/outfalls", token)
    assert status == 200, status
    return next(o["id"] for o in body["items"] if o["outfall_code"] == OUTFALL_CODE)


def create_payload(of_id: int, code: str) -> dict:
    return {
        "outfall_id": of_id,
        "permit_ref": PERMIT,
        "sample_code": code,
        "flow_m3h": 88.0,
        "metrics": {"cod": 20.0, "nh3n": 1.0, "tp": 0.1},
    }


def formal_codes(token: str) -> set[str]:
    status, body = call("GET", "/api/samples", token)
    assert status == 200, status
    return {s["sample_code"] for s in body["items"] if s.get("permit_ref") == PERMIT}


def main() -> int:
    print(f"[ping_permit_lock] target={PERMIT} lock_key={LOCK_KEY} base={base_url()}")
    admin = login("admin", "admin123")
    writer = login("writer", "writer123")
    of_id = outfall_id(admin)
    failures: list[str] = []

    # ---- 1) 占锁 + Barrier 真并发：后到必须全部 409、零批、留争用痕 ----------
    status, _ = call("POST", f"/api/locks/acquire?lock_key={urllib.parse.quote(LOCK_KEY)}", writer)
    if status != 200:
        print(f"[ping_permit_lock] FAIL acquire lock status={status}")
        return 1
    print("[ping_permit_lock] writer acquired", LOCK_KEY)

    n = 4
    barrier = threading.Barrier(n)
    results: list[tuple[str, int]] = []
    rlock = threading.Lock()

    def held_worker(i: int) -> None:
        barrier.wait(timeout=10)
        code, body = call(
            "POST",
            "/api/samples",
            admin,
            create_payload(of_id, f"SM-PING-HELD-{int(time.time())}-{i}"),
        )
        with rlock:
            results.append((f"admin-{i}", code))

    threads = [threading.Thread(target=held_worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    print("[ping_permit_lock] held-burst statuses:", results)
    if any(code != 409 for _, code in results):
        failures.append(f"占锁期间并发同号建批应全 409，实际 {results}")

    _, locks_body = call("GET", "/api/locks", admin)
    traces = [
        x for x in locks_body.get("contention", []) if x.get("lock_key") == LOCK_KEY
    ]
    print(f"[ping_permit_lock] contention traces for {LOCK_KEY}: {len(traces)}")
    if not traces:
        failures.append("缺少 permit:DP-E55 争用痕")

    call("POST", f"/api/locks/release?lock_key={urllib.parse.quote(LOCK_KEY)}", writer)

    held_prefix = "SM-PING-HELD-"
    dp_rows = formal_codes(admin)
    leaked_held = [c for c in dp_rows if c.startswith(held_prefix)]
    if leaked_held:
        failures.append(f"占锁并发败方出现正式批: {leaked_held}")

    # ---- 2) 不预占锁的两路真并发裸抢：安全不变量（无 2xx / 零批） -----------
    pair_barrier = threading.Barrier(2)
    raw: list[tuple[str, int]] = []

    def raw_worker(name: str, token: str, idx: int) -> None:
        code_name = f"SM-PING-RAW-{int(time.time()*1000)}-{idx}"
        pair_barrier.wait(timeout=10)
        code, _ = call("POST", "/api/samples", token, create_payload(of_id, code_name))
        with rlock:
            raw.append((name, code))

    t1 = threading.Thread(target=raw_worker, args=("writer", writer, 0))
    t2 = threading.Thread(target=raw_worker, args=("admin", admin, 1))
    t1.start(); t2.start(); t1.join(timeout=30); t2.join(timeout=30)
    print("[ping_permit_lock] raw-pair statuses:", raw, "（允许 400/409，禁止 2xx）")
    if any(code < 300 for _, code in raw):
        failures.append(f"DP-E55 无许可裸抢不得成功建批: {raw}")
    leaked_raw = [c for c in formal_codes(admin) if c.startswith("SM-PING-RAW-")]
    if leaked_raw:
        failures.append(f"裸抢出现正式批: {leaked_raw}")

    if failures:
        for f in failures:
            print("[ping_permit_lock] FAIL:", f)
        return 1
    print(f"[ping_permit_lock] OK {PERMIT} 同号许可锁互斥成立：败方零批、争用痕在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
