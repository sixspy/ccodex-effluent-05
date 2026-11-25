# 污水排放批（effluent）

数据工程母仓：处理厂采样入库 → 超标旁路挂起 → 准排放裁定 → 封批升代 → 排放许可对账。

## 骨架一句话

采样批次入库后裁定超标才准排放封批，驳回进旁路挂起，指标血缘与排放许可对账。

## effluent-05 无许可禁建（2026-11-25 拍板，当日封死）

> 决议状态：**甲路径 · 当日封死**。验收号：排污戊第 5 槽 / effluent-05 独验收段。

- **拍板口径（甲路径）**：许可册对 `permit_ref` **无匹配行**（如 `DP-E55`）时，采样写口 `POST /api/samples` 一律拒收（400，响应头 `X-Effluent-Permit-Block: no_permit`），**采样正式册 `sample_batches` 零增**；本机种子目录 `fixtures/` 同样执行该闸，无许可预置批 `SM-E55` 不得被 `seed_samples` 盲插成“入库假绿”。
- **两边不得混用**：入库准入口只做“许可册有无匹配行 + 状态是否有效”；许可-指标帽的账实对齐仍归对账服务的 `validate_permit_match`。不得用对账匹配或任何单点许可查询去“一查救三红”。
- **不要第三路**：不引入“无许可先写影子、升正再进正式册”的乙路径，也不开任何旁路/开关。任何要求影子放行、第三路、或“只改采样页提示条”的偏离，统一记归类码 **`无许可禁建偏航`**（落 `permit_block_log.block_kind`，接口侧 403 + 头 `pianhang`）并**拒写**。
- **许可锁**：建批占键为 `permit:{许可号}`（另持 `outfall:{id}` 仅护编号生成）。两路会话同号 `DP-E55` 并发抢建必须互斥：占锁期间后到者 409、正式册零批，并在 `contention_log` 留 `lock_key=permit:DP-E55 / 争用失败` 痕。并发脚本：`python scripts/ping_permit_lock.py [base_url]`（打同号 `DP-E55`）。
- **五页同源**（同一 FastAPI + SQLite，禁各造口径）：
  1. 采样页：许可号与 `/api/permits` 同源比对，无匹配则建批键 `disabled` 并明示“无许可禁建”，后端同闸拒收；
  2. 许可页：许可册查无 `DP-E55`（`/api/permits/DP-E55` 404），`/api/permits/interceptions` 列同源拦截痕，并提供匹配核查；
  3. 对账页：`GET /api/reconcile` 的 `summary` 流量累计只计有许可匹配的正式批，无许可批列入 `excluded_no_permit` 且流量计入 `excluded_no_permit_flow_m3h`；另有 `/api/reconcile/no-permit`；
  4. 排放口页：`GET /api/outfalls/{id}/formal-samples` 与详情 `formal_samples` 经 `JOIN discharge_permits` 只列有许可匹配的正式批，不含无许可号；
  5. 总览页：`/api/dashboard` 的 `permit_blocked`（别名 `no_permit_blocked`/`permit_block_count`）与采样拒收、许可页痕同源 `permit_block_log`，拒收一次加一。

### 测闸（先红后绿，未跑红测不得合入）

三红先分别落 `tests/test_effluent_05_jia.py`、`tests/test_effluent_05_yi.py`、`tests/test_effluent_05_zheng.py` 并在未改服务前实测见红（甲=无许可仍成正式批/零增被破，乙=对账无剔除累计口径，争=许可锁缺失只撞 400）；见红齐后才动采样、许可、对账、排放口四服务与采样页、许可页。三红分服务救绿，禁止单点许可匹配交差。

```bash
PYTHONPATH=backend python -m pytest tests/test_effluent_05_jia.py -q     # 甲：零增拒收/计数/同源投影
PYTHONPATH=backend python -m pytest tests/test_effluent_05_yi.py -q      # 乙：对账流量剔除无许可批
PYTHONPATH=backend python -m pytest tests/test_effluent_05_zheng.py -q   # 争：permit:DP-E55 许可锁
python scripts/ping_permit_lock.py http://127.0.0.1:8000                 # 两路并发打同号
```

## 一键起环境

```bash
docker compose up -d --build
```

浏览器访问 http://localhost:11600

- 管理账号：`admin` / `admin123`
- 读写账号：`writer` / `writer123`
- 只读账号：`viewer` / `viewer123`

## 本地开发

```powershell
cd projects/14-effluent
$env:PYTHONPATH="backend"
python -m uvicorn app:app --app-dir backend --reload --port 8000
```

## 自测

```powershell
$env:PYTHONPATH="backend"
python -m pytest
python scripts/count_loc.py
```
