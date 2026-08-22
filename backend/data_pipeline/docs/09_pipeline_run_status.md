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

## 待办任务分解与实现方案（Loop Engineering）

每个未完成任务拆成同一种循环：**Discover（探查原因/数据源）→ Implement（改代码/建表/登记源）→ Validate（重新校验）→ Publish & Sync（发布+同步业务表）**——这四步本来就是pipeline自身的结构（采集→解析→校验→staging→enrichment→发布→同步），新任务复用同一套循环，不重新发明流程。收敛条件（DoD）写清楚，避免"做了但不知道算不算完"。

### 推荐执行顺序（按依赖关系）

```
①#6/#8 逐分段表修复 ──▶ ②#5/#7 投档线转valid+发布
③#4 policy发布（独立，最快能关掉）
④#11-embed 补现有4条chunk的embedding（独立bug修复，工作量S，建议插队提前）
⑤#9 专业录取线（10校适配，可与⑥并行）
⑥#10 主数据建表 + #11剩余（10校3类文档采集，两者共享同一批页面调研，建议合并执行）
⑦#12 教育部标准目录（弱依赖⑥，采集本身可提前做）
```

### #4　2025招生政策发布

- **DoD**：6条全部`valid`（或明确标记不可解析并注明理由），发布`jiangsu_2025_policy_v1`
- **Discover**：读那1条`needs_review`的`issues_json`，确认是`volunteer_mode_missing`还是`max_volunteers_missing`，回查官方原文判断是文本真的没写还是解析器漏识别
- **Implement**：解析器漏识别→补`parsers/document.py`正则；原文本身缺失→走`POST /admin/data-pipeline/review/{id}`人工approve并注明理由
- **Publish**：当前没有policy专用发布脚本（只有admission_score/rank_segment/admission_plan三个），需新写`scripts/publish_jiangsu_policy.py`，复用`PipelineRepository.publish(dataset_type="policy", ...)`
- 工作量：S（半天）

### #5 + #7　2023/2024投档线（186条needs_review）

- **DoD**：2023/2024各自发布一个dataset_version，valid覆盖率≥90%（对齐PRD §8验收线）
- **强依赖 #6/#8**：现在186条卡住的根因是逐分段表覆盖率太低，不是没跑enrichment，对186条直接调`apply_admission_score_enrichment`跑不出新结果
- **Implement**：`scripts/publish_jiangsu_admission_scores.py`第32行`YEAR = 2025`硬编码，需改造成接受`--year`参数（或复制成2023/2024两个版本），复用2025年"enrichment → 人工核对原图补`manual_rank_overrides` → 发布"的模式
- **Validate**：关联不上位次的记录人工核对原图（同2025年那4条的处理方式），非批量推算
- 工作量：M（每年半天~1天，取决于#6/#8修复程度）

### #6 + #8　2023/2024逐分段表解析修复

- **DoD**：valid比例达到2025年同等水平（271/295≈92%），作为#5/#7的输入
- **Discover**：对照官方原图逐行核对当前解析失败原因（复用2025年"累计人数列读成同分人数列"的根因分析方法，见`08_jiangsu_data_pipeline_handoff.md §3.5`）
- **Implement**：改`parsers/tabular.py::_read_image`表格解析分支，适配2023/2024版式差异（列宽/表头位置很可能与2025不同，需要重新调，不是重跑一次就行）
- **Validate**：重跑采集，对比`valid_records`数量是否显著提升
- 工作量：L（OCR/版式适配；Linux环境跑不了这步，需在macOS或先接PaddleOCR）

### #9　10校专业录取线

- **DoD**：按PRD §8验收线，官方公开覆盖率≥90%，未公开的院校明确标记缺失（不推算）
- **Discover**：逐校排查招生网是否公开"专业录取分数线"页面（区别于院校整体投档线），10校逐个确认
- **Implement**：官方文件→复用`AdmissionScoreRecord`+现有admission_score parser；JS动态页面→复用#3已验证的`collection_method: manual` + Playwright路径
- **Publish**：`AdmissionScoreRecord`本身支持`major_group_code`/`major_code`维度，不需要新模型，新写`scripts/publish_jiangsu_major_scores.py`即可
- 工作量：M-L（10校逐个适配，参考#3的10校经验）

### #10　院校/学院/专业主数据

- **DoD**：院校层字段补全；学院/专业层建表并至少完成10校覆盖
- **Discover/Design**：
  - 院校层：`enrollment_data_universities`加`admissions_url`一列（一行migration，`jiangsu.yaml`里数据已有，直接同步）
  - 学院/专业层：设计`enrollment_data_colleges`（名称/所属院校/生效年份）、`enrollment_data_majors`（专业标准代码/名称/专业类/学制/学位/所属学院/校区/开设状态），字段对齐PRD §3.2D
- **Implement**：alembic迁移建表 → `data_pipeline/records.py`新增`CollegeRecord`/`MajorRecord` → `business_sync.py`补对应sync逻辑
- **Collect**：10校"学院设置"+"专业介绍"页面采集，大概率复用#3的manual playwright路径——**建议和#11合并采集动作**，同一批页面能同时产出主数据字段和RAG chunk
- 工作量：L（新表设计 + 10校采集）

### #11　章程/专业介绍/转专业政策RAG（含修复现有数据）

- **DoD**：现有4条chunk补齐embedding；10校×3类文档至少各1条可检索chunk且带embedding
- **先修bug**：现有1个policy文档的4条chunk全部`embedding IS NULL`——`repository.py::_sync_rag_chunks`只管写chunk正文，没有调用`app/engine/embedding.py::embed_batch`。需要补一个批处理脚本（如`scripts/embed_pending_chunks.py`），扫`rag_chunks.embedding IS NULL`批量补embedding，这一步不依赖新数据源，工作量S，建议优先做
- **新数据源**：逐校找章程/专业介绍/转专业政策入口 → 登记数据源 → 复用`parsers/document.py`语义chunk逻辑（policy这条路已验证可行）→ `stage_records()`自动写入`rag_documents`/`rag_chunks` → 跑embedding脚本 → 抽样检索验证
- 工作量：M（补embedding脚本S + 10校×3类文档采集L）

### #12　教育部院校/专业标准目录

- **DoD**：导入标准代码目录，作为#10专业主数据的代码校验基准
- **Discover**：找教育部/阳光高考官网公开的院校/专业标准目录下载入口
- **Implement**：登记数据源，复用现有Excel/HTML解析路径（大概率是静态文件，不需要Playwright）
- **Publish**：写入`enrollment_data_majors`标准代码字段（弱依赖#10先建表，采集本身可以提前做）
- 工作量：S-M

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
- RAG chunk入库和embedding生成是两步分开的：`stage_records()`只负责把chunk正文写进`rag_chunks`，不会自动调`app/engine/embedding.py::embed_batch`——现有4条chunk全是`embedding IS NULL`的活例子，新增RAG数据源时不要漏了这一步
