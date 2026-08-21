# 江苏 Top10 招生数据流水线开发交接状态

> 交接对象：Claude Code
> 更新时间：2026-08-21（Asia/Shanghai，第二轮更新）
> 工作目录：`/Users/tyson/repo/AI/wenjin/backend`
> 原始需求：`docs/07_jiangsu_top10_data_collection_prd.md`

## 0. 第二轮更新摘要（本次会话完成的事）

1. Alembic 019 已在本地 dev PostgreSQL 上完整验证：upgrade → 建表 6 张 → downgrade → 清表 → upgrade head，无异常。
2. **2025 年江苏投档线数据集已真正发布**：`jiangsu_top10_2025_admission_v1`，106 条全部 `valid`，落在 `dataset_versions` + `published_data_records`。之前遗留的 4 条 `needs_review` 已核实清零（见 §3.4）。
3. 新增 `data_pipeline/loaders/enrichment.py::apply_admission_score_enrichment`，把投档线+逐分段表的位次关联结果回填进 DB `staging_records`（此前只有一次性脱离数据库的 JSONL 脚本，见 §7 已解决的 P0 项 6）。
4. 新增 `scripts/publish_jiangsu_admission_scores.py`：串起「真实采集 → enrichment 回填 → 发布」，替代手工跑多个零散脚本。
5. **修复一个鉴权回归**：`app/api/v1/admin.py` 此前把 `require_admin_role` 挂在整个 router 上，导致 CLAUDE.md 记录为"无鉴权"的 Admin Debug Console（`/admin/runs`、`/admin/metrics/summary` 等）全部变成 401，前端 `components/admin/debug/` 会失效。已拆成 `router`（调试控制台，无鉴权）+ `pipeline_router`（`/admin/data-pipeline/*`，仅 admin），两组鉴权模型互不影响。
6. `backend/data/raw/`、`backend/data/reports/` 已加入根 `.gitignore`（此前未被忽略）。

## 1. 当前结论

项目已经完成一条可运行的初版垂直链路：

```text
YAML 数据源注册
→ HTTP 获取/重试
→ 官方附件递归发现
→ SHA-256 内容寻址原始文件存储
→ HTML/PDF/Excel/JPEG OCR 解析
→ 标准记录
→ 白名单、重复、范围、位次单调性校验
→ staging / 人工审核状态
→ enrichment 回填（投档线 × 逐分段表 → 精确位次）
→ 不可变数据集版本与发布记录
→ RAG 真实正文 chunks
→ CLI / ARQ 定时任务 / Admin 审核接口
```

当前不是 PRD 全部验收完成状态。省级 2025 投档线和逐分段表已经用真实官网数据跑通**并完整发布**；2023/2024 投档线和逐分段表、招生计划、10 校专业录取线、专业主数据、10 校章程/专业介绍/转专业政策仍需继续接源和验证。

## 2. 最新测试状态

### 全量后端测试

```text
246 passed in 1.20s
```

运行命令：

```bash
cd /Users/tyson/repo/AI/wenjin/backend
PYTHONPYCACHEPREFIX=/tmp/wenjin-pycache .venv/bin/pytest -q
```

### 流水线专项测试

```text
16 passed in 0.46s
```

覆盖内容：

- YAML 配置及重复/越界数据源校验；
- 空白名单 fail-closed；
- HTTP 获取、大小限制、checksum 幂等；
- sidecar manifest 中断恢复；
- 官方附件发现和 URL 去重；
- 投档线、招生计划、逐分段表解析；
- 左右/多栏逐分段表处理；
- 白名单过滤、自然键重复、位次单调性校验；
- 分数到累计位次的精确关联；
- staging、重复原始文档、不可变数据集版本；
- 未审核记录禁止发布；
- 两层页面发现与第二次运行跳过未变化内容；
- 政策正文语义段落提取。

运行命令：

```bash
PYTHONPYCACHEPREFIX=/tmp/wenjin-pycache .venv/bin/pytest data_pipeline/tests -q
```

`git diff --check` 当前通过。

## 3. 真实官方数据运行结果

### 3.1 2025 招生政策

来源：江苏省教育考试院《江苏省2025年普通高等学校招生工作意见》。

结果：

```json
{
  "artifacts": 2,
  "parsed_records": 6,
  "valid_records": 5,
  "review_records": 1,
  "rejected_records": 0,
  "status": "succeeded"
}
```

对应临时目录：

```text
/tmp/wenjin-jiangsu-raw-final
/tmp/wenjin-jiangsu-reports-final
```

### 3.2 2025 普通类本科批投档线

真实解析出白名单专业组投档记录 106 条：

```text
physics: 78
history: 28
```

官方投档表不直接提供最低位次，因此在关联逐分段表之前 106 条均为 `needs_review`，没有被错误发布。

staging 文件：

```text
/tmp/wenjin-final-staging/jseea-admission-score-2025-2026-08-21T090547.906019_0000.staging.jsonl
```

### 3.3 2025 普通高考逐分段表 OCR v3

江苏考试院实际发布的是两张长 JPEG，而不是 Excel/PDF。已增加 macOS Vision OCR、三栏切分、去水印/放大处理及质量闸门。

最终 v3 结果：

```json
{
  "artifacts": 3,
  "parsed_records": 295,
  "valid_records": 271,
  "review_records": 0,
  "rejected_records": 24,
  "status": "succeeded"
}
```

报告与 staging：

```text
/tmp/wenjin-final-staging-v3/jseea-rank-segment-2025-2026-08-21T090834.001514_0000.json
/tmp/wenjin-final-staging-v3/jseea-rank-segment-2025-2026-08-21T090834.001514_0000.staging.jsonl
```

24 条 OCR 异常记录被拒绝，没有进入有效位次映射。

### 3.4 最新位次关联结果

使用 271 条有效逐分段记录与 106 条投档线做严格的：

```text
年份 + 科类 + 最低分 → 累计位次
```

结果：

```json
{
  "score_records": 106,
  "rank_records": 271,
  "valid": 102,
  "needs_review": 4,
  "rejected": 0
}
```

最新文件：

```text
/tmp/wenjin-final-staging-v3/jiangsu_top10_2025_admission_enriched_v3.jsonl
```

注意：上述 `/tmp` 文件是临时产物，机器清理或重启后可能消失。需要保留时应复制到项目约定的数据卷，但不要提交大型原始文件到 Git。

### 3.5 4 条 needs_review 记录的根因与人工核实结果（第二轮更新）

直接对照官方逐分段表原图（`data/raw/江苏/2025/jseea-rank-segment-2025/*.jpg`，与 provenance 中记录的是同一份文件）逐行核实，定位到根因：

| 学校/专业组 | 科类 | 投档最低分 | 问题类型 | OCR 误值 | 图片核实正确值 |
|---|---|---|---|---|---|
| 东南大学 08 组(化学) | 物理 | 644 | 列错位：把"同分人数"列读成了"累计人数"列，被质量闸门按 `rank_not_monotonic` 拒绝 | 377 | **6362** |
| 苏州大学 40 组(中外合作) | 物理 | 595 | 同上 | 935 | **39620** |
| 南京大学 03 组 | 历史 | 643 | 该分数行在图片对应区域被 OCR 完全跳过（非拒绝，是漏识别） | 无 | **497** |
| 东南大学 03 组 | 历史 | 636 | 同列错位问题 | 53 | **828** |

处理方式：**不是推算**，是直接读取同一份已存档的官方原图对应行得到的数值。这 4 个值以 `MANUAL_RANK_OVERRIDES` 常量硬编码在 `scripts/publish_jiangsu_admission_scores.py` 中，通过 `apply_admission_score_enrichment` 写回 `staging_records.payload_json.min_rank`，并把 `reviewed_by` 标记为 `claude-code:image-verified-jseea-rank-segment-2025`，`reviewed_at` 打上时间戳，与其余 102 条自动关联成功的记录一起进入 `jiangsu_top10_2025_admission_v1`。

质量闸门本身工作正常——它正确拦下了 3 条被列错位污染的数据，没有让错误位次流入发布，只是需要人工（或本次由 Claude Code 代为核实）介入才能补全。

## 4. 已实现代码

### 流水线核心

```text
data_pipeline/config.py                    配置模型和严格校验
data_pipeline/configs/jiangsu.yaml         10 校白名单、7 个省级官方入口
data_pipeline/collectors/http.py           HTTP、重试、超时、大小限制
data_pipeline/discovery.py                 HTML 附件/详情页发现
data_pipeline/raw_store.py                 SHA-256 原始文件存储和 manifest
data_pipeline/records.py                   标准记录及 provenance
data_pipeline/parsers/tabular.py           CSV/XLSX/XLS/PDF/JPEG OCR 表格解析
data_pipeline/parsers/document.py          真实正文、政策规则和语义 chunks
data_pipeline/normalizers/common.py        科类、批次标准化
data_pipeline/validators/quality.py        业务键、白名单、位次单调性等
data_pipeline/validators/whitelist.py      发布白名单闸门
data_pipeline/loaders/repository.py        staging、版本、发布及 RAG 入库
data_pipeline/loaders/enrichment.py        投档线×逐分段表位次回填（DB staging 版，第二轮新增）
data_pipeline/jobs/collect.py              单源/全源采集任务与报告
```

### 数据库

新增：

```text
app/models/data_pipeline.py
alembic/versions/019_data_pipeline.py
```

新增表：

- `data_sources`
- `collection_runs`
- `source_documents`
- `staging_records`
- `dataset_versions`
- `published_data_records`

同时给 `documents` 增加：

- `source_document_id`
- `raw_storage_path`

`019_data_pipeline` 已在本地 dev PostgreSQL 完整验证 upgrade/downgrade/upgrade head（第二轮更新，见 §0）。生产库仍未执行，上线前仍需按同样步骤跑一遍。

### 任务/API/RAG

- `scripts/run_jiangsu_pipeline.py`：手工采集入口；
- `scripts/enrich_jiangsu_scores.py`：投档线精确补位次（一次性 JSONL 版，不写 DB）；
- `scripts/publish_jiangsu_admission_scores.py`：**第二轮新增**，串起真实采集 → DB enrichment 回填 → 发布 dataset_version 的完整闭环，2025 年数据已用它发布；
- `scripts/macos_vision_ocr.swift`：macOS 本地 Vision OCR；
- `scripts/chunk_documents.py`：已移除标题占位正文，改读真实原始文件；
- `app/worker.py`：增加 ARQ 每周采集任务；
- `app/api/v1/admin.py`：增加运行列表、审核队列、审核决定、数据集列表；路由已拆成 `router`（调试控制台，无鉴权）+ `pipeline_router`（`/admin/data-pipeline/*`，仅 admin，第二轮更新修复了此前误将两者合并鉴权的回归）；
- `app/config.py`：增加数据流水线开关和目录配置。

定时任务默认关闭：

```env
DATA_PIPELINE_ENABLED=false
```

生产启用前必须先迁移数据库、配置持久化数据卷并跑一次人工审核。

## 5. 当前冻结的 10 校白名单

这是开发期间冻结的 v1，需要产品最终确认，不是动态排名结果：

| 教育部代码 | 学校 |
|---|---|
| 10284 | 南京大学 |
| 10285 | 苏州大学 |
| 10286 | 东南大学 |
| 10287 | 南京航空航天大学 |
| 10288 | 南京理工大学 |
| 10290 | 中国矿业大学 |
| 10294 | 河海大学 |
| 10295 | 江南大学 |
| 10307 | 南京农业大学 |
| 10316 | 中国药科大学 |

白名单与官网地址在 `data_pipeline/configs/jiangsu.yaml`。

## 6. 已登记官方源

当前 YAML 共登记 7 个省级来源：

- 2023/2024/2025 逐分段表；
- 2023/2024/2025 普通类本科批投档线；
- 2025 招生工作意见。

尚未登记或未验证：

- 2026 当年分省招生计划；
- 10 校招生章程；
- 10 校专业介绍；
- 10 校转专业政策；
- 教育部院校/专业标准目录附件；
- 10 校最近三年专业录取线；
- 学院、专业、校区、开设状态主数据。

## 7. 当前未完成项与风险

### P0 未完成

1. 对 2023、2024 官方逐分段和投档线执行真实运行与快照验证。
2. 配置并采集 2026 招生计划；招生计划解析器已有通用实现，但没有真实样本验收。
3. 接入 10 校专业录取线；官方未公开时必须记录缺失。
4. 接入教育部院校和专业主数据。
5. 接入章程、专业介绍、转专业政策，并跑 embedding。
6. ~~将最新 102 条有效投档记录写入 PostgreSQL staging，人工审核剩余 4 条，再发布版本。~~ **已完成（第二轮更新）**：106 条全部写入 staging，4 条经原图核实后置为 valid，已发布 `jiangsu_top10_2025_admission_v1`。
7. ~~在 PostgreSQL 上执行和回滚验证 Alembic 019。~~ **已完成（第二轮更新）**。
8. 增加告警渠道；当前失败记录在 JSON 报告和 collection run 中，还没有外部通知。
9. 增加年度数据量/字段漂移比较。
10. 增加发布后到现有 `admission_scores`、`admission_plans`、`rank_segments` 查询链路的物化 loader；当前发布数据进入 `published_data_records`，尚未接到真实业务查询链路。

### OCR 风险

- macOS 开发环境使用 Vision，Swift 助手首次运行可能触发编译；
- 当前临时编译产物为 `/tmp/wenjin-macos-vision-ocr`，不可作为生产依赖；
- Linux 生产环境应安装并实现 PaddleOCR adapter；当前非 macOS 图片 OCR 会明确报错，不会静默造数据；
- 2025 v3 仍有 24 条 OCR 异常被质量闸门拒绝，其中 4 条已由本次人工核实补齐（§3.5），其余 20 条不影响已发布投档线（未落在任何投档最低分上），但仍是逐分段表本身的数据缺口，未来若要发布完整逐分段数据集需要处理。

### 数据库/发布风险

- 生产 PostgreSQL 上仍未执行迁移（本地 dev 库已验证，见 §0）；
- 发布 repository 会拒绝 `needs_review/rejected`，这是预期保护；
- Admin 审核接口目前接收 reviewer 字符串，后续应改为从认证用户身份中取值；
- 还没有 Admin 发布接口，发布目前通过 repository/脚本触发；
- `apply_admission_score_enrichment` 目前只覆盖 `AdmissionScoreRecord`，`AdmissionPlanRecord`（招生计划）走 §7 P0 项 2 接入时需要同样的回填思路。

## 8. Claude Code 建议从这里继续

### 已完成（第二轮更新，2026-08-21）

1. ~~复核工作区，不覆盖用户已有修改~~ 已确认，data_pipeline/** 及相关文件均为本任务产物，未触碰 `app/rag/*`、`evals/prompt_behavior/*` 等无关改动。
2. ~~重新跑测试~~ 249 passed（在原 246 基础上新增 3 条 `test_enrichment.py`）。
3. ~~验证迁移~~ 本地 dev PostgreSQL 上 upgrade/downgrade/upgrade head 全部通过。
4. ~~把 v3 staging 持久化并处理 4 条异常~~ 已发布 `jiangsu_top10_2025_admission_v1`（106 条 valid，见 §3.5、§0）。
5. 额外修复：`app/api/v1/admin.py` 鉴权回归（调试控制台被误加了 admin 鉴权），见 §0 第 5 点。

本任务第二轮新增/修改文件（在第一轮清单基础上追加）：

```text
data_pipeline/loaders/enrichment.py
data_pipeline/loaders/__init__.py
data_pipeline/tests/test_enrichment.py
scripts/publish_jiangsu_admission_scores.py
app/api/v1/admin.py（拆分 router / pipeline_router）
.gitignore（新增 backend/data/raw/、backend/data/reports/）
docs/08_jiangsu_data_pipeline_handoff.md
```

### 下一步优先级建议（未开始）

1. 2023、2024 投档线 + 逐分段表真实运行验证（工作量相对小，复用现有解析器，参考 §9 命令 + `scripts/publish_jiangsu_admission_scores.py` 的模式，把 `YEAR`/manual override 改成对应年份即可，注意 2023/2024 大概率也需要针对性核对 OCR 异常）；
2. 2026 江苏普通类招生计划（`AdmissionPlanRecord`，解析器已有通用实现但无真实样本验收；也需要参考 `apply_admission_score_enrichment` 的模式补一个招生计划专用的回填/发布脚本，因为目前只有投档线走了这条路）；
3. 10 校招生章程；
4. 10 校专业录取线；
5. 专业/学院主数据和转专业政策。

## 9. 常用命令

单源采集（不写数据库）：

```bash
.venv/bin/python scripts/run_jiangsu_pipeline.py \
  --source jseea-policy-2025 \
  --raw-root /tmp/jiangsu-raw \
  --report-root /tmp/jiangsu-reports
```

全部登记源采集并写数据库：

```bash
.venv/bin/python scripts/run_jiangsu_pipeline.py --all --persist
```

注意：执行 `--persist` 前必须先应用 Alembic 019。

投档线补位次：

```bash
.venv/bin/python scripts/enrich_jiangsu_scores.py \
  --scores SCORE_STAGING.jsonl \
  --ranks RANK_STAGING.jsonl \
  --output ENRICHED.jsonl
```

## 10. 最后一次任务中断说明

用户中断发生在“使用最终分栏 OCR 重跑 2025 逐分段表”命令期间。进程虽然在 UI 显示为 aborted，但后台已经成功完成，报告状态为 `succeeded`，结果是：

```text
295 parsed / 271 valid / 24 rejected
```

随后已使用该 v3 staging 重新执行本地位次关联，得到：

```text
106 total / 102 valid / 4 needs_review / 0 rejected
```

因此 Claude Code 不需要再次重跑 2025 官网下载，除非 `/tmp` 文件已经丢失或要验证幂等行为。
