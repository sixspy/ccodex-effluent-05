#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""effluent-05 并发脚本入口（根目录垫片）。

真正实现见 scripts/ping_permit_lock.py；此处允许直接在仓库根执行：
    python ping_permit_lock.py [base_url]
"""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "scripts" / "ping_permit_lock.py"
    runpy.run_path(str(target), run_name="__main__")
