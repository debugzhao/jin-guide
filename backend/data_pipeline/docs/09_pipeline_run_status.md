# 江苏 Top10 数据采集 — 任务执行状态看板

> 更新时间：2026-08-22 | 数据来源：直查 PostgreSQL（`pipeline_staging_records`/`pipeline_published_data_records`/`pipeline_collection_runs`/`enrollment_data_*`），非文档推断
> 用途：随时查看每个任务当前卡在哪一步，快速定位下一步命令，不用重新翻代码

## 状态图例

✅ 完成（已发布+已同步业务表） ｜ ⚠️ 部分完成（有产出但卡在某一步） ｜ ❌ 未开始（无数据/无表结构）

## 任务看板

| # | 任务 | 状态 | 产出 | 卡点 / 下一步 |
|---|---|---|---|---|
| 1 | 2025 投档线（`admission_score`） | ✅ | 106条valid → 已发布`1efdcec7` → 已同步`enrollment_data_admission_scores` | 无 |
| 2 | 2025 逐分段表（`rank_segment`） | ✅ | 271条valid（24条OCR异常拒收）→ 已发布`236d1ef8` → 已同步 | 无 |
| 3 | 2026 招生计划（10校，`admission_plan`） | ✅ | 491条valid（10校全覆盖，Playwright人工采集）→ 已发布`63527a04` → 已同步`enrollment_data_admission_plans` | 无。**注意：README/08号文档仍写"架构性卡住/未开始"，是旧结论，已过期** |
| 4 | 2025 招生政策（`policy`） | ⚠️ | 6条解析（5 valid + 1 needs_review） | 未发布。下一步：核实1条needs_review后跑发布脚本（当前只有admission_score/rank_segment各有专用发布脚本，policy没有，需要新写或复用`PipelineRepository.publish`） |
| 5 | 2023 投档线 | ⚠️ | staging 84条，**全部**`needs_review` | 未做位次关联（enrichment）。下一步：先跑#6把2023逐分段表修好，再跑`apply_admission_score_enrichment`补位次 |
| 6 | 2023 逐分段表 | ⚠️ | staging仅1条valid（OCR/解析几乎全军覆没） | 需重新排查解析失败原因（大概率OCR列错位，参考2025年"累计人数列错位"那类坑），工作量视为"重新调"而非"跑一下" |
| 7 | 2024 投档线 | ⚠️ | staging 102条，**全部**`needs_review` | 同#5，等#8修好后关联位次 |
| 8 | 2024 逐分段表 | ⚠️ | staging仅3条valid | 同#6 |
| 9 | 10校专业录取线 | ❌ | 0 | 未登记数据源，PRD要求官方未公开则明确标记缺失，不可推算 |
| 10 | 院校/学院/专业主数据 | ❌ | 院校层：`enrollment_data_universities`已有大部分字段；学院/专业层：0（无表） | 院校层缺`admissions_url`一列（加列即可）；学院/专业层无实体表，`major_name`只是交易表里的自由文本列，不能当主数据用 |
| 11 | 10校章程/专业介绍/转专业政策（RAG） | ❌ | `rag_documents`仅1条（policy），`rag_chunks`仅4条 | 未登记数据源；**且现有4条chunk全部`embedding IS NULL`**，RAG检索链路对已有数据实际也不可用，不只是"没做新的" |
| 12 | 教育部院校/专业标准目录 | ❌ | 0 | 未登记数据源 |
| 13 | 业务表同步 loader | ✅ | `sync_published_data_to_business_tables.py` 已跑，#1#2#3全部同步 | 每次全量重扫，数据量涨上去后可加增量游标（当前不必要） |

## 关键数字核对（DB实查，2026-08-22）

```text
pipeline_staging_records 按 record_type/review_status：
  AdmissionPlanRecord   valid=491
  AdmissionScoreRecord  valid=106  needs_review=186（=2023的84 + 2024的102）
  RankSegmentRecord     valid=275（=2025的271 + 2023的1 + 2024的3）  rejected=24
  PolicyRuleRecord      valid=5   needs_review=1
  DocumentChunkRecord   valid=4

pipeline_published_data_records：
  AdmissionPlanRecord   491条 → dataset_version 63527a04
  AdmissionScoreRecord  106条 → dataset_version 1efdcec7
  RankSegmentRecord     271条 → dataset_version 236d1ef8

enrollment_data_admission_scores/rank_segments/admission_plans 里的"河南"数据是历史mock种子，与江苏真实数据不冲突。
```

## 快速恢复命令

```bash
# 查当前staging/发布状态（不用每次进DB手写SQL）
.venv/bin/python scripts/run_jiangsu_pipeline.py --source <source_id> --raw-root /tmp/jiangsu-raw --report-root /tmp/jiangsu-reports

# 2023/2024 投档线补位次+发布（照抄2025年模式，改YEAR）
.venv/bin/python scripts/publish_jiangsu_admission_scores.py   # 需要先确认脚本里YEAR/MANUAL_RANK_OVERRIDES改成对应年份

# 逐分段表发布（同理）
.venv/bin/python scripts/publish_jiangsu_rank_segments.py

# 业务表同步（幂等，可重复跑）
.venv/bin/python scripts/sync_published_data_to_business_tables.py
```

## 已知会卡住的坑（复现前必读）

- OCR 依赖 macOS Vision（`scripts/macos_vision_ocr.swift`），Linux 上会明确报错，不接受静默造数据
- 2023/2024 逐分段表解析效果差是真实现象，不是环境问题，需要人工核对原图（参考2025年"累计人数列错位"根因分析，见 `08_jiangsu_data_pipeline_handoff.md` §3.5）
- 招生计划类数据源官网多为JS动态渲染，`HttpCollector`结构性接不了，只能走`collection_method: manual`的Playwright人工辅助路径（已验证可行，见任务#3）
