# P0-B Search Provider 与搜索快照

当前实现版本：`bilibili-public-search.p0-b.1` / `search-import.p0.1`

## 范围

P0-B 只负责建立任务执行时最多 5 页的 B 站公开搜索快照，并保存逐页状态、规范化实体、按 crawl run 冻结的视频/创作者观测和覆盖记录。它不实现 Top 5 竞品评分、代表视频、确定性商业指标或 `IntelligenceReport`。

搜索结果是执行时可获得的公开快照，不是 B 站全站穷举；第一次运行不能证明增长趋势。

## Provider 契约

业务编排只依赖 `SearchProvider`：

- `capabilities`：Provider 名称、版本、类型、搜索/账号样本能力、原生排序/时间/分区条件、登录要求和商业授权状态。
- `search_page(request, page_number, cancel_check)`：返回统一 `SearchPage`、`Video`、`Creator` 和仅供调用方选择性留存的原始载荷。
- `close()`：释放 Provider 自有连接。

当前能力：

| Provider | 类型 | 登录 | 原生能力 | 商业边界 |
|---|---|---:|---|---|
| `bilibili-public-search` | development | 否 | 相关度、最新、最多播放排序 | 仅低频开发和验证，不代表生产授权或稳定 SLA |
| `import` | import | 否 | 严格复现导入快照声明的排序/时间/分区 | 权利取决于导入数据来源，不自动获得商业授权 |
| `fixture` | fixture | 否 | 固定脱敏响应 | 只用于自动化测试 |

平台不原生支持的时间、分区、`min_view` 和 `max_duration_seconds` 条件由统一规范化层后置过滤，并写入 `local_filters`。未知过滤条件直接拒绝，不静默忽略。

## Development Provider

- 不使用用户个人 Cookie，不要求 Token、账号或密码。
- 不绕过登录、验证码、访问控制或风控。
- 每个 SearchRequest 只循环 `1..max_pages`，冻结契约将 `max_pages` 限制为 1～5；代码不会请求第 6 页。
- 每页记录首次请求时间、完成时间、耗时、请求 URL、原始数量、规范化数量、原始响应 SHA-256、原生/本地过滤、错误码和可读摘要。
- 默认单页超时 10 秒、最多 2 次重试、指数退避和请求间隔；`429/5xx`、网络错误和超时有限重试，风控/权限类响应不会无限重试。
- 取消在分页、退避、限流和在途 HTTP 请求期间检查；取消页标记 `cancelled`，后续页不再请求。
- `empty` 是成功响应页；`failed`、`timeout`、`cancelled` 不计入成功响应页。
- 只有响应明确包含空 `result` 列表时才记为 `empty`；`v_voucher` 等风控挑战或缺少结果列表的响应记为失败，不能伪装成空页。

开发接口变化、风控或偶发成功都不能被描述为生产可用性或商业授权。

## Import Provider

Import Provider 支持 JSON 和 CSV。输入使用同一规范化输出，不允许绕过 BVID、MID、缺失字段、分页状态或请求元数据约束。

JSON 顶层格式：

```json
{
  "schema_version": "search-import.p0.1",
  "source_name": "customer-export-or-public-manual-snapshot",
  "provider_version": "source-version",
  "snapshot_at": "2026-07-16T00:00:00Z",
  "keyword": "sanitized-keyword",
  "sort_mode": "relevance",
  "time_range": "all",
  "partition": null,
  "pages": [
    {
      "page_number": 1,
      "status": "success",
      "source_url": "https://example.test/public-search",
      "results": [
        {
          "bvid": "BV1000000001",
          "title": "sanitized-title",
          "source_url": "https://www.bilibili.com/video/BV1000000001",
          "creator_mid": "10001",
          "creator_name": "sanitized-creator"
        }
      ]
    }
  ]
}
```

CSV 每行必须声明相同的 `source_name`、`provider_version`、`keyword`、`snapshot_at`、排序/时间/分区元数据，以及 `page_number`、`page_status`。视频行使用 `bvid`、`title`、`video_source_url`；空页或失败页可以留空视频字段。未知列、缺失必需列、跨行元数据不一致、非法 BVID、成功页无结果、空/失败页带结果都会被拒绝。完整脱敏样例在 `tests/fixtures/search_provider/`。

导入的 `keyword`、排序、时间和分区必须与 SearchRequest 一致；缺页记为 `IMPORT_PAGE_MISSING`，不能用导入数据静默补造请求页。人工补充的参考账号不得混入原始 `pages[].results`。

## 规范化、去重和状态

- 每页 `raw_result_count` 是 Provider 原始列表长度；`normalized_result_count` 是字段校验和本地过滤后的结果数。
- 视频按 BVID 跨页去重，创作者按 MID 去重；保留视频首次出现页码和排名。
- MID 缺失时保持 `null`，不会生成假 MID；可选字段缺失保持 `null` 并进入 `missing_fields`。
- 0 个成功响应页：`failed` 或 `cancelled`。
- 1～请求页数减 1 个成功响应页：`partial`，保存所有已尝试页和截断原因。
- 全部请求页成功但无视频：`empty`，不能生成正常报告。
- 全部请求页成功且有视频：搜索快照 `success`。

P0-B 的 `actual_competitor_count` 固定为 0。即使搜索快照成功，本阶段也不生成竞品排名或情报报告。

## API、Worker 与数据库

旧 `POST /jobs` 请求不传 `task_mode` 时仍走 `legacy` LangGraph 分析路径。P0-B 请求示例：

```json
{
  "query": "建立B站某关键词当前搜索快照",
  "platforms": ["bilibili"],
  "analysis_mode": "standard",
  "task_mode": "content_intelligence",
  "keyword": "sanitized-keyword",
  "sort_mode": "relevance",
  "time_range": "all",
  "partition": null,
  "max_pages": 5,
  "filters": {},
  "search_provider": "development",
  "idempotency_key": "caller-stable-idempotency-key"
}
```

Worker 将任务级元数据和页状态写入 `crawl_runs`、`search_pages`。`videos`、`creators` 保存按 BVID/MID 归一化的最新实体，可供复用或缓存；`crawl_run_videos`、`crawl_run_creators` 保存本次 crawl run 实际观测到的完整视频和创作者字段，是历史搜索快照的冻结数据源。后续任务即使命中相同 BVID/MID 并更新全局实体，也不会改写旧任务的标题、指标、Provider 或观测时间。

同一 Job 重复执行复用唯一 `crawl_run`，在一个事务中替换该 run 的页、视频观测和创作者观测，不产生重复关联；不同 Job 的 observation 完全隔离。失败、部分成功、空结果和取消仍保存逐页记录；删除 Job 或 crawl run 时只级联清理其运行记录和 observation，不误删全局规范实体或其他任务的 observation。正常报告表不会在 P0-B 路径创建记录。

查询：`GET /jobs/{job_id}/search-snapshot`。响应包括覆盖、逐页状态、去重视频和候选账号；视频和创作者字段只从该 crawl run 的 observation 读取，不再关联全局最新实体；仍执行任务所有权校验。重试已入队但新快照尚未原子替换时，旧结果显式标记 `attempt_state=previous_attempt`，避免伪装成当前重试结果。

不可变 observation 由 Alembic revision `20260716_0003` 引入；旧 `crawl_run_videos` 数据在升级时从当时的全局视频/创作者实体回填。

## 验证

```powershell
# P0-B Provider/分页/导入/持久化/API
.\.venv\Scripts\python.exe -m pytest -q tests\test_search_providers.py tests\test_search_snapshot_integration.py tests\test_product_api.py

# P0-A 定向回归
.\.venv\Scripts\python.exe -m pytest -q tests\test_intelligence_contracts.py tests\test_intelligence_metrics.py

# 完整 Python 回归
.\.venv\Scripts\python.exe -m pytest -q
```

20 关键词真实冒烟使用 `scripts/run_p0b_smoke.py`，输入仓库外人工基线并把完整原始响应、规范化结果和重合率保存到仓库外新目录。`scripts/audit_p0b_hardcoding.py` 使用同一私有基线扫描候选提交，只输出哈希化命中标识，不打印私有关键词、MID 或账号名。

## 生产 Provider 合同问题清单

生产接入前必须书面确认：

- 是否允许自动化关键词搜索、分页和账号/视频元数据读取。
- 是否允许商业使用、缓存、保存历史快照和生成衍生报告。
- 是否允许向终端客户展示来源字段、链接和聚合结果。
- 数据保留、删除、地域、隐私和安全要求。
- 速率限制、并发限制、SLA、错误语义和版本变更通知。
- 是否允许转售、再分发或仅限内部分析。

未完成上述确认前，Development Provider 不能改名或包装为 production/authorized Provider。
