# 江苏 Top10 数据采集 — 任务执行状态看板

> 更新时间：2026-08-22 | 数据来源：直查 PostgreSQL（`pipeline_staging_records`/`pipeline_published_data_records`/`pipeline_collection_runs`/`enrollment_data_*`），非文档推断
> 用途：随时查看每个任务当前卡在哪一步，快速定位下一步命令，不用重新翻代码

## 状态图例

✅ 完成（已发布+已同步业务表） ｜ ⚠️ 部分完成（有产出但卡在某一步） ｜ ❌ 未开始（无数据/无表结构） ｜ 🛑 阻塞在外部依赖（非代码问题，需要人决策/协调）

## 任务看板

| # | 任务 | 状态 | 产出 | 卡点 / 下一步 |
|---|---|---|---|---|
| 1 | 2025 投档线（`admission_score`） | ✅ | 106条valid → 已发布`1efdcec7` → 已同步`enrollment_data_admission_scores` | 无 |
| 2 | 2025 逐分段表（`rank_segment`） | ✅ | 271条valid（24条OCR异常拒收）→ 已发布`236d1ef8` → 已同步 | 无 |
| 3 | 2026 招生计划（10校，`admission_plan`） | ✅ | 491条valid（10校全覆盖，Playwright人工采集）→ 已发布`63527a04` → 已同步`enrollment_data_admission_plans` | 无。**注意：README/08号文档仍写"架构性卡住/未开始"，是旧结论，已过期** |
| 4 | 2025 招生政策（`policy`） | ✅ | 已发布`jiangsu_policy_2025_policy_v1`（1条valid） | 无。needs_review那条是入口HTML空壳重复（无正文，非解析bug），已标记`rejected`并注明原因，见`scripts/publish_jiangsu_policy.py` |
| 5 | 2023 投档线 | ⚠️ | staging 84条，**全部**`needs_review` | 未做位次关联（enrichment）。下一步：先跑#6把2023逐分段表修好，再跑`apply_admission_score_enrichment`补位次 |
| 6 | 2023 逐分段表 | ⚠️ | staging仅1条valid（OCR/解析几乎全军覆没） | 需重新排查解析失败原因（大概率OCR列错位，参考2025年"累计人数列错位"那类坑），工作量视为"重新调"而非"跑一下" |
| 7 | 2024 投档线 | ⚠️ | staging 102条，**全部**`needs_review` | 同#5，等#8修好后关联位次 |
| 8 | 2024 逐分段表 | ⚠️ | staging仅3条valid | 同#6 |
| 9 | 10校专业录取线 | ❌ | 0 | 未登记数据源，PRD要求官方未公开则明确标记缺失，不可推算 |
| 10 | 院校/学院/专业主数据 | ❌ | 院校层：`enrollment_data_universities`已有大部分字段；学院/专业层：0（无表） | 院校层缺`admissions_url`一列（加列即可）；学院/专业层无实体表，`major_name`只是交易表里的自由文本列，不能当主数据用 |
| 11 | 10校章程/专业介绍/转专业政策（RAG） | 🛑 | `rag_documents`仅1条（policy），`rag_chunks`仅4条，全部`embedding IS NULL` | **阻塞在外部账户权限，不是代码问题**：`scripts/chunk_documents.py --embed-only`现成可用，但LiteLLM转发到`openai/moonshot-v1-emb-small`时返回`403 The API you are accessing is not open`——Moonshot账户没开通embedding模型权限。需要业务决策：找Moonshot开通，或换litellm_config.yaml里其他可用的embedding模型（后者与CLAUDE.md"后端是Moonshot Kimi"的约定冲突，需确认） |
| 12 | 教育部院校/专业标准目录 | ❌ | 0 | 未登记数据源 |
| 13 | 业务表同步 loader | ✅ | `sync_published_data_to_business_tables.py` 已跑，#1#2#3全部同步 | 每次全量重扫，数据量涨上去后可加增量游标（当前不必要） |

## 待办任务分解与实现方案（Loop Engineering）

每个未完成任务拆成同一种循环：**Discover（探查原因/数据源）→ Implement（改代码/建表/登记源）→ Validate（重新校验）→ Publish & Sync（发布+同步业务表）**——这四步本来就是pipeline自身的结构（采集→解析→校验→staging→enrichment→发布→同步），新任务复用同一套循环，不重新发明流程。收敛条件（DoD）写清楚，避免"做了但不知道算不算完"。

### 推荐执行顺序（按依赖关系）

```
①#6/#8 逐分段表修复 ──▶ ②#5/#7 投档线转valid+发布
③#4 policy发布（独立，最快能关掉）                                      ✅ 已完成 2026-08-22
④#11-embed 补现有4条chunk的embedding（独立bug修复，工作量S，建议插队提前）    🛑 阻塞在Moonshot账户权限，2026-08-22
⑤#9 专业录取线（10校适配，可与⑥并行）
⑥#10 主数据建表 + #11剩余（10校3类文档采集，两者共享同一批页面调研，建议合并执行）
⑦#12 教育部标准目录（弱依赖⑥，采集本身可提前做）
```

### #4　2025招生政策发布 —— ✅ 已完成（2026-08-22）

- **DoD**：6条全部`valid`（或明确标记不可解析并注明理由），发布`jiangsu_2025_policy_v1`
- **Discover结果**：那1条`needs_review`来自jseea.cn的入口HTML公告页（只是一段指向PDF附件的announcement blurb），本身不含政策正文，`volunteer_mode`/`max_volunteers`等字段全部为空——不是解析器漏识别，是这份文档真的没有内容。同批次的PDF附件解析出的另一条记录字段齐全，已是`valid`
- **处理方式**：两条记录的`natural_key`相同（province+year+batch+subject_type，不含文档维度），若强行把空壳记录也改成`valid`会在发布时因`natural_key`重复被`PipelineRepository.publish`拦截，且违反"不编造缺失字段"的原则——因此把空壳记录标记`rejected`并在`reviewed_by`注明原因，只发布内容完整的那1条
- **产出**：新增`scripts/publish_jiangsu_policy.py`，发布`jiangsu_policy_2025_policy_v1`（1条记录）
- **遗留**：`PolicyRuleRecord`目前只发布到`pipeline_published_data_records`，还没有对应的`business_sync.py::sync_policy`把它同步进`enrollment_data_rule_requirements`业务表（该表已建好但当前0行，且没有任何查询代码引用它）——这是新发现的一个小缺口，不在本次#4范围内，留给后续任务

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

### #11-embed　补现有chunk的embedding —— 🛑 阻塞在外部账户权限（2026-08-22）

- **DoD**：现有4条chunk补齐embedding，抽样检索验证能命中
- **Discover结果（结论被上一版文档写错了）**：不需要新写脚本——`scripts/chunk_documents.py --embed-only`本来就存在，内部调的是`app/engine/embedding.py::embed_pending_chunks()`，逻辑（扫`embedding IS NULL` → 批量调`embed_batch` → 写回`chunk.embedding`/`embedding_model`）本来就是完整的
- **实际执行**：`docker compose exec backend python -m scripts.chunk_documents --embed-only` 跑起来后，LiteLLM转发到`openai/moonshot-v1-emb-small`时返回 `403 - {"message": "The API you are accessing is not open"}`（litellm容器日志确认，重试2次后fallback也失败）。根因是**当前Moonshot API Key没有开通embedding模型（`moonshot-v1-emb-small`）的访问权限**，是账户/套餐层面的限制，不是代码bug，脚本本身工作正常
- **需要人决策，不是代码能解决的**：
  1. 找Moonshot开通该模型权限（改动最小，维持"embedding也走Moonshot"的现有架构约定）
  2. 换`litellm_config.yaml`里其他已开通权限的embedding模型（会跟CLAUDE.md"模型网关实际后端是Moonshot Kimi"的既有约定冲突，需要明确决定是否接受）
- 工作量：一旦权限打通，实际执行是S（跑一条现成命令）；卡点在决策/协调，不在工程

### #11-collect　新增10校章程/专业介绍/转专业政策数据源

- **DoD**：10校×3类文档至少各1条可检索chunk且带embedding（依赖#11-embed先解除阻塞）
- **Discover**：逐校找章程/专业介绍/转专业政策入口
- **Implement**：登记数据源 → 复用`parsers/document.py`语义chunk逻辑（policy这条路已验证可行）→ `stage_records()`自动写入`rag_documents`/`rag_chunks`
- **Validate**：跑embedding（依赖#11-embed的阻塞先解除）→ 抽样检索验证
- 工作量：L（10校×3类文档采集）

### #12　教育部院校/专业标准目录

- **DoD**：导入标准代码目录，作为#10专业主数据的代码校验基准
- **Discover**：找教育部/阳光高考官网公开的院校/专业标准目录下载入口
- **Implement**：登记数据源，复用现有Excel/HTML解析路径（大概率是静态文件，不需要Playwright）
- **Publish**：写入`enrollment_data_majors`标准代码字段（弱依赖#10先建表，采集本身可以提前做）
- 工作量：S-M

## 关键数字核对

```text
2026-08-22 初次核实：
  pipeline_staging_records 按 record_type/review_status：
    AdmissionPlanRecord   valid=491
    AdmissionScoreRecord  valid=106  needs_review=186（=2023的84 + 2024的102）
    RankSegmentRecord     valid=275（=2025的271 + 2023的1 + 2024的3）  rejected=24
    PolicyRuleRecord      valid=5   needs_review=1
    DocumentChunkRecord   valid=4（全部embedding IS NULL）

  pipeline_published_data_records：
    AdmissionPlanRecord   491条 → dataset_version 63527a04
    AdmissionScoreRecord  106条 → dataset_version 1efdcec7
    RankSegmentRecord     271条 → dataset_version 236d1ef8

2026-08-22 执行#4后更新：
  PolicyRuleRecord: valid=1（发布）+ rejected=1（空壳重复，之前那1条needs_review的去向）
  pipeline_published_data_records 新增：PolicyRuleRecord 1条 → dataset_version jiangsu_policy_2025_policy_v1
  DocumentChunkRecord 4条仍是 embedding IS NULL（#11-embed执行失败，见任务看板#11）

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

# policy发布（已执行过，幂等重跑安全）
.venv/bin/python scripts/publish_jiangsu_policy.py

# 补chunk embedding（当前会因Moonshot账户权限403失败，权限打通后直接跑这条即可，不用改代码）
docker compose exec backend python -m scripts.chunk_documents --embed-only
```

容器内执行注意：本项目backend容器`WORKDIR`是`/app`，要用`python -m scripts.xxx`（模块方式）而不是`python scripts/xxx.py`，否则`from app.xxx import ...`会报`ModuleNotFoundError: No module named 'app'`。

## 已知会卡住的坑（复现前必读）

- OCR 依赖 macOS Vision（`scripts/macos_vision_ocr.swift`），Linux 上会明确报错，不接受静默造数据
- 2023/2024 逐分段表解析效果差是真实现象，不是环境问题，需要人工核对原图（参考2025年"累计人数列错位"根因分析，见 `08_jiangsu_data_pipeline_handoff.md` §3.5）
- 招生计划类数据源官网多为JS动态渲染，`HttpCollector`结构性接不了，只能走`collection_method: manual`的Playwright人工辅助路径（已验证可行，见任务#3）
- RAG chunk入库和embedding生成是两步分开的：`stage_records()`只负责把chunk正文写进`rag_chunks`，不会自动调embedding——但补embedding的脚本（`scripts/chunk_documents.py --embed-only`）本来就有，不用新写。真正的坑是**Moonshot账户没开通`moonshot-v1-emb-small`的调用权限**（LiteLLM返回403 `The API you are accessing is not open`），这是账户层面的外部阻塞，遇到同样403要先怀疑账户权限，不要以为是代码或脚本缺失
