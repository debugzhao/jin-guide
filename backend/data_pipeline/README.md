# data_pipeline — 江苏 Top10 高校招生数据采集流水线

只服务江苏省 + `configs/jiangsu.yaml` 里冻结的 10 所目标高校白名单。目标：把官方公开的投档线、位次表、招生政策等数据，通过可追溯、可重跑的流程采集下来，最终喂给推荐引擎和 RAG，替代原本的 mock/seed 数据。

产品需求见 `docs/07_jiangsu_top10_data_collection_prd.md`；开发过程与遗留问题的详细记录见 `docs/08_jiangsu_data_pipeline_handoff.md`（本文档只梳理"代码实际怎么跑"，不重复交接细节）。

## 一、端到端链路

```
configs/jiangsu.yaml（人工登记的官方入口页 + 白名单）
        │
        ▼
HttpCollector（httpx 直连官方 URL，带重试/大小限制/User-Agent 标识）
        │
        ▼
discover_links()（在入口页 HTML 里用正则找附件/详情页链接，避免每年硬编码文件名）
        │
        ▼
RawArtifactStore（SHA-256 内容寻址落盘 raw 文件 + 不可变 sidecar manifest，checksum 不变则跳过重复下载/重复入库）
        │
        ▼
parsers/*（按 data_type 分派：tabular.py 处理 CSV/XLSX/PDF/JPEG OCR；document.py 处理 HTML/PDF 正文）
        │
        ▼
validate_records()（白名单校验 + 自然键重复检测 + 位次单调性检测 + 必填字段检测，失败即挂 issues 不阻断）
        │
        ▼
staging_records 表（review_status: valid / needs_review / rejected）
        │
        ▼（仅 AdmissionScoreRecord 需要，因为官方投档表不直接给位次）
apply_admission_score_enrichment()（投档线 × 逐分段表按"年份+科类+最低分"精确关联出 min_rank，写回 staging）
        │
        ▼
PipelineRepository.publish()（只接受全部 valid 的 staging 记录，生成不可变 dataset_versions + published_data_records）
        │
        ▼
sync_all()（★ 本次新增，见 §4）把 published_data_records 同步进 admission_scores / rank_segments / admission_plans
        │
        ▼
推荐引擎 SQL 精确查询（app/engine/retrieval.py::search_admission_sql）真正用上这批数据
```

RAG 分支：`document`/`policy`/`charter`/`major_intro`/`transfer_policy` 类型的记录（`DocumentChunkRecord`）在 `stage_records()` 里被同步写入 `documents`/`chunks` 表（`PipelineRepository._sync_rag_chunks`），不经过 publish 这一步——因为它们本来就是给 pgvector 检索用的语义片段，没有"发布版本"这个概念。

## 二、目录结构与职责

```
data_pipeline/
├── config.py               Pydantic 配置模型：PipelineConfig/SourceConfig/TargetUniversity，
│                            白名单唯一性 + 数据源引用白名单校验在这里做（模型加载时就拦，不用等到运行期）
├── configs/jiangsu.yaml     人工审计官网后手写的 10 校白名单 + 数据源登记表（不是爬取/自动生成）
├── collectors/http.py       HttpCollector：httpx 请求 + 指数退避重试 + 响应体大小上限
├── discovery.py             discover_links()：解析入口页 HTML，按标题正则找附件/详情页链接
├── raw_store.py             RawArtifactStore：SHA-256 内容寻址存储 + JSON sidecar manifest
├── records.py               Pydantic 记录模型：RankSegmentRecord/AdmissionScoreRecord/
│                            AdmissionPlanRecord/DocumentChunkRecord/PolicyRuleRecord + Provenance
├── parsers/
│   ├── tabular.py           CSV/XLSX/XLS/PDF（pdfplumber）/JPEG（macOS Vision OCR，见下方"OCR 依赖"）
│   │                        表格解析 -> 上面几种 Record
│   └── document.py          HTML/PDF 正文抽取、按语义段落切 chunk、招生政策规则抽取（志愿模式/最大志愿数等）
├── normalizers/common.py    科类（物理/历史）、批次名称标准化
├── validators/
│   ├── quality.py           natural_key()（业务自然键哈希）、validate_records()（重复/位次单调性/
│   │                        必填字段校验）、attach_min_ranks()（投档线×逐分段表关联）
│   └── whitelist.py         require_whitelisted_university()：非白名单高校 fail-closed，不静默丢弃
├── loaders/
│   ├── repository.py        PipelineRepository：sync_sources/register_document/stage_records/
│   │                        publish（发布前校验全部 valid、按 record_type 单一化、自然键不冲突）
│   ├── enrichment.py        apply_admission_score_enrichment()：投档线关联位次后写回 staging
│   └── business_sync.py     ★ 本次新增：published_data_records -> admission_scores/rank_segments/
│                            admission_plans 的 loader，见下方 §4
├── jobs/collect.py          PipelineJob：串起"采集 -> 附件发现 -> 解析 -> 校验 -> 落 staging"整条链路，
│                            对外暴露 run_source()/run_all()，落一份 JSON 运行报告 + JSONL staging 快照
└── tests/                   每个模块都有对应单测，用 SQLite 内存库跑 DB 相关测试
```

## 三、当前真实进度（不是 PRD 全部完成状态）

| 数据类型 | PRD 范围 | 当前状态 |
|---|---|---|
| 2025 江苏投档线（`admission_score`） | 2023-2025 | ✅ 已采集、已关联位次、已发布（`jiangsu_top10_2025_admission_v1`，106 条 valid）、✅ 已同步进 `admission_scores` |
| 2025 逐分段表（`rank_segment`） | 2023-2025 | ✅ 已采集（OCR，271 条 valid）、✅ 已发布（`jiangsu_policy_2025_rank_segment_v1`，`scripts/publish_jiangsu_rank_segments.py`）、✅ 已同步进 `rank_segments` |
| 2025 招生政策（`policy`） | 2025 | ✅ 已采集（6 条解析记录），未发布 |
| 2023/2024 投档线、逐分段表 | 2023-2025 | ❌ YAML 已登记入口，未真实运行验证 |
| 招生计划（`admission_plan`） | 2026 当年 | ❌ **数据源被证实无法用现有架构采集**，见下方"已知限制"——不是没找 URL，是真的接不了 |
| 专业录取线、专业/学院主数据、章程/专业介绍/转专业政策 | P0/P1 | ❌ 未开始 |

## 四、业务表同步（`loaders/business_sync.py`，本次补上的环节）

`published_data_records` 和推荐引擎实际查询的 `admission_scores`/`rank_segments`/`admission_plans` 是刻意分离的两层——发布区可以任意重跑/回滚版本，不会因为一次采集问题污染业务表。但在这次补之前，这道"发布区 -> 业务表"的 loader 完全不存在（`docs/08_jiangsu_data_pipeline_handoff.md` §7 P0 第 10 项遗留问题），106 条已发布的投档线只是"发布归档"，推荐引擎实际查的 `admission_scores` 一直是空的。

现在跑：

```bash
.venv/bin/python scripts/sync_published_data_to_business_tables.py
```

行为要点：

- 只读 `published_data_records`，不读 `staging_records`——数据必须显式 publish 过才能进业务表，这是分层设计的意义所在。`AdmissionScoreRecord`/`RankSegmentRecord` 已经发布并同步（分别用 `scripts/publish_jiangsu_admission_scores.py`/`scripts/publish_jiangsu_rank_segments.py`），`AdmissionPlanRecord` 还没有任何数据被采集过，所以现在跑这个脚本它会显示 `seen: 0`，不是 bug，等真的采到数据发布后自动就能同步，不需要改代码。
- 目标 10 校里有 8 所原本不在 `universities` 表（现有 51 条是别的省份的 mock 种子数据），loader 会按 `jiangsu.yaml` 的 code/name 自动建院校记录，985/211/双一流状态按公开事实手动核对填入 `business_sync.py::_UNIVERSITY_META`（这是学校基本信息，不算"招生数据推测"）。
- `admission_scores.major_category` 填的是 `major_group_name`（如"南京航空航天大学05专业组(化学)"）——`admission_scores` 原有 51 条老数据这个字段全是 NULL（院校整体线），但 `search_admission_sql` 本就允许同一院校下出现多行、`risk_engine.py` 也按 `major_category` 做扎堆检测，所以填专业组粒度是符合现有查询设计的，不是新发明的用法。
- 幂等：`admission_scores`/`admission_plans` 没有数据库唯一约束防重复插入，loader 在应用层按业务自然键先查后写，可以重复跑不产生重复行（`rank_segments` 本身有唯一约束，行为保持一致）。

## 五、常用命令

```bash
# 单源采集，不写数据库（调试用）
.venv/bin/python scripts/run_jiangsu_pipeline.py \
  --source jseea-policy-2025 --raw-root /tmp/jiangsu-raw --report-root /tmp/jiangsu-reports

# 全部登记数据源采集并写数据库（--persist 前必须先 alembic upgrade head）
.venv/bin/python scripts/run_jiangsu_pipeline.py --all --persist

# 串起"采集 2025 投档线+逐分段表 -> 关联位次 -> 发布 dataset_version"完整闭环
.venv/bin/python scripts/publish_jiangsu_admission_scores.py

# 发布已采集验证过的 2025 逐分段表（★ 本次新增）
.venv/bin/python scripts/publish_jiangsu_rank_segments.py

# 把已发布数据同步进业务表（★ 本次新增，见 §4）
.venv/bin/python scripts/sync_published_data_to_business_tables.py

# 单测（全量 + 流水线专项）
cd backend && PYTHONPYCACHEPREFIX=/tmp/wenjin-pycache .venv/bin/pytest -q
PYTHONPYCACHEPREFIX=/tmp/wenjin-pycache .venv/bin/pytest data_pipeline/tests -q
```

## 六、已知限制

- **OCR**：2025 逐分段表官方发的是长 JPEG 而不是表格文件，`parsers/tabular.py::_read_image` 依赖 `scripts/macos_vision_ocr.swift`（macOS 系统 Vision API）。Linux 生产环境目前**明确报错，不会静默造假数据**，还没接 PaddleOCR 等跨平台方案。
- **动态页面 / 无 Playwright**：只用 `httpx` 直连，没有接 Playwright；如果某个官方页面改成纯前端渲染，`discover_links()` 会直接找不到附件链接（表现为 `artifacts=1`，只拿到入口页本身）。**招生计划（`admission_plan`）就是撞在这个限制上**：实测（2026-08-21）江苏省考试院公告页只公布汇总数字，原文写"《2026招生计划专刊》将送达考生"——详细的院校/专业组/计划人数数据是印刷专刊，不是网站文件；省考试院的"查询中心"（`cxzx.jseea.cn`/`stat.jseea.cn`）和南京大学本科招生网（`bkzs.nju.edu.cn`）抓下来都只有页面外壳，是 JS 动态渲染的查询系统/站点，`HttpCollector` 结构性接不了；全网搜索也没找到任何一份分省分专业招生计划的公开 PDF/Excel（只搜到投档线文件，是另一类数据）。PRD（§4）预留的退路是"高校招生网分省计划 → 官方合作数据文件 → 合法授权数据源 → **人工导入**"——如果要接这块数据，大概率要走人工导入这条路，或者先给 pipeline 加 Playwright 采集能力（且还要验证能不能绕开查询系统的表单交互），这是比"登记一个 URL"大得多的独立工作量，本次没有做。
- **定时任务默认关闭**：`app/worker.py` 的 `run_jiangsu_data_collection` ARQ 定时任务受 `DATA_PIPELINE_ENABLED`（默认 `false`）控制，生产启用前必须先跑迁移、配置持久化数据卷、跑一轮人工审核。
- **业务表同步是"重扫全量"**：`business_sync.py` 每次都会重新处理全部 `published_data_records`，不是只处理"上次同步之后新增的"——数据量小（目前 106 条）时无所谓，量级涨上去后如果觉得慢，可以按 `dataset_version_id` 或 `created_at` 加增量游标，现在没做是因为没必要。
