# 上海 Top10 数据采集 — 任务执行状态看板

> 创建时间：2026-08-22 | 复用江苏 pipeline 架构（`data_pipeline/`），架构/代码不重新发明，只新增 `configs/shanghai.yaml` + `scripts/*_shanghai_*.py`
> 目标高校（已与产品侧确认，4所985+5所211+1所行业强校）：
> 复旦大学、上海交通大学、同济大学、华东师范大学、上海财经大学、上海外国语大学、华东理工大学、东华大学、上海大学、上海理工大学
> 用途：随时查看每个任务当前卡在哪一步，快速定位下一步命令，不用重新翻代码。参考江苏看板：`09_pipeline_run_status.md`

## 状态图例

✅ 完成（已发布+已同步业务表） ｜ ⚠️ 部分完成（有产出但卡在某一步） ｜ ❌ 未开始（无数据/无表结构） ｜ 🛑 阻塞在外部依赖（非代码问题，需要人决策/协调）

## 任务看板

| # | 任务 | 状态 | 产出 | 卡点 / 下一步 |
|---|---|---|---|---|
| 0a | 数据源审计（上海市教育考试院官网 `shmeea.edu.cn` + 10校招生网） | ✅ | 见下方「Discover 阶段结论」 | 无 |
| 0b | 建 `configs/shanghai.yaml` | ✅ | 已建，10校+14个source，`load_pipeline_config` 校验通过 | 无。东华源已注册但 `enabled: false`（架构性阻塞，见#3） |
| 1 | 2025 投档线（`admission_score`） | 🛑 | 无 | **架构阻塞，非"跑一下"**：`records.py::SubjectType = Literal["physics","history"]` 硬编码物理/历史二分，上海"3+3"不分文理，现有 schema 装不下。需要产品/架构决策后才能写 `shmeea_admission_score_v1` 解析器，见下方「需要决策」 |
| 2 | 2025 逐分段表（`rank_segment`） | 🛑 | 无 | 同 #1 的 SubjectType 阻塞；且上海不发逐分明细表，发的是《成绩分布区间表》PDF，结构与江苏完全不同，`parse_rank_segment_rows` 不能复用，需要新写 `shmeea_score_distribution_v1` |
| 3 | 2026 招生计划（10校，`admission_plan`） | ⚠️ | **8/10校已采集到原始结构化数据**，落地 `data/raw/上海/2026/admission-plan-manual/`：华东师范大学(39行)、上海外国语大学(22专业)、同济大学(13专业)、华东理工大学(35专业，与页面概况604人核对一致)、上海大学(36专业，2078人)、上海理工大学(20专业/类，1377人)、上海财经大学(25专业，319人，图片验证码人工识别通过)、**上海交通大学(19专业，197人，报纸版式整页图片，用网格线检测+人工视觉核对，与图片自带"总计"行197完全对账一致)** | **发布逻辑因 SubjectType 阻塞暂缓，见下方需要决策#1**。剩余2所：复旦大学官网"招生计划"栏目最新只到2024年，2025/2026年未发布（WebSearch多方核实，非我方没找到——官方招生动态/报考指南栏目均无对应文件，本科分省分专业计划这类年份文件复旦大学近两年未公开发布到自己网站，按PRD"官方未公开则标记缺失"处理，不推算不使用2024年旧数据顶替）；东华大学 🛑 官网明确写数据仅在微信小程序内查询，网页端无任何可采集入口，Playwright 也无法处理小程序，已在 yaml 里标记 `enabled: false`，需产品侧决策替代方案 |
| 4 | 2025 招生政策（`policy`） | ⚠️ | 已跑通采集+解析（未落库）：11个文档（主页HTML+10个PDF附件）→ 25条staging记录（14条`DocumentChunkRecord`全部valid + 11条`PolicyRuleRecord`：3条valid、8条needs_review），`run_shanghai_pipeline.py --source shmeea-policy-2025` 全流程无报错 | **发布前需人工核对，不能照抄江苏发布脚本逻辑直接发**：与江苏"入口页空壳、附件完整"的情况相反，上海是主页HTML本身`needs_review`（缺`max_volunteers`），3条valid的PolicyRuleRecord来自3个不同"志愿表样表"PDF附件（`5.pdf`→4、`6.pdf`→3、`8.pdf`→24），这10个PDF大概率对应不同批次（提前批/艺体类/本科批/专项等）的样表，需要人工打开原PDF逐一核实每条的`batch`归属和数字含义是否真的是"最大志愿数"，且要检查这些记录的`natural_key`（province+year+batch+subject_type）是否会互相冲突——盲目发布有编造/张冠李戴风险 |
| 5 | 2023 投档线 | ❌ | 无 | 依赖 #6，与 #7/#8 同批规划，非本轮 P0 |
| 6 | 2023 逐分段表 | ❌ | 无 | 非本轮 P0，视 #1-#4 完成情况决定是否推进 |
| 7 | 2024 投档线 | ❌ | 无 | 依赖 #8，非本轮 P0 |
| 8 | 2024 逐分段表 | ❌ | 无 | 非本轮 P0 |
| 9 | 10校专业录取线 | ❌ | 无 | 需逐校排查官网是否公开"专业录取分数线"（区别于院校投档线），未公开则明确标记缺失，不推算 |
| 10 | 院校/学院/专业主数据 | ❌ | 无 | 院校层：`enrollment_data_universities` 加 10 校记录；学院/专业层复用江苏已设计的表结构（若 #10 江苏那边已建表则直接复用，不重复建） |
| 11 | 10校章程/专业介绍/转专业政策（RAG） | ❌ | 无 | 🛑 已知会卡在 Moonshot 账户 embedding 权限（`moonshot-v1-emb-small` 403），与江苏 #11 同一个外部阻塞，采集本身不受影响，chunk 入库后 embedding 步骤会卡住 |
| 12 | 业务表同步 | ❌ | 无 | 直接复用现成的 `scripts/sync_published_data_to_business_tables.py`（province 无关，不需要新写代码） |

## Discover 阶段结论（2026-08-22，WebSearch/WebFetch 实测，未编造URL）

### 省级数据源（上海市教育考试院 `www.shmeea.edu.cn`）

| 数据类型 | 结论 |
|---|---|
| 逐分段表 | 上海不发逐分明细表，发《本科录取控制分数线上考生高考成绩分布表》等区间分布PDF：`page/09000/20250623/19549.html`（入口页，含12个PDF附件） |
| 投档线 | 只找到PDF直链（`download/20250719/186.pdf`普通批次、`185.pdf`Q组中外合作），未找到承载下载链接的公告母页面；本科普通批次是"院校专业组"平行志愿，不分物理/历史；**580分及以上考生分数线官方不公开**，发布时必须如实标记缺失 |
| 招生政策 | `page/06300/20250425/19280.html`，页面本身即政策全文HTML（非入口页+附件模式），可直接复用 `policy_document_v1` |

### 10校招生计划页

| 学校 | 代码 | 结论 |
|---|---|---|
| 复旦大学 | 10246 | 静态HTML，但数据是PNG图片非文本表格，需OCR；列表页最新只到2024年，2025/2026条目未定位到，采集前需人工重新确认 |
| 上海交通大学 | 10248 | JS动态SPA（`admissions.sjtu.edu.cn`），需Playwright |
| 同济大学 | 10247 | JS动态查询系统，需选省份才渲染表格 |
| 华东师范大学 | 10269 | JS动态AJAX模板渲染（`zsbcx.ecnu.edu.cn`），与江苏南大同一套模板系统 |
| 上海财经大学 | 10272 | JS动态查询系统，**带4位数字图片验证码**，比其他学校多一道人工/OCR障碍 |
| 上海外国语大学 | 10271 | 同华师大同模板系统 |
| 华东理工大学 | 10251 | Vue SPA（`bkzsdata.ecust.edu.cn`），纯前端渲染 |
| 东华大学 | 10255 | 🛑 官网公告明确写"计划数据仅在微信小程序内查询"，网页端无查询系统无PDF，Playwright无法处理小程序 |
| 上海大学 | 10280 | JS动态（ASP.NET+AJAX grid），需Playwright |
| 上海理工大学 | 10252 | JS动态（四级下拉+查询按钮），典型交互模式 |

## 需要人决策的架构问题（🛑，不是"跑一下"能解决的）

1. **`SubjectType` schema 冲突 —— 已被并行的浙江任务解决，但未提交，暂不能用**：`data_pipeline/records.py` 里 `SubjectType = Literal["physics", "history"]` 是江苏"物理类/历史类"选科模式的硬编码假设。2026-08-22 发现工作区里有另一个并行会话在做**浙江**Top10采集，已经把 `SubjectType` 扩展成 `Literal["physics","history","unified"]` 并在 `jobs/collect.py` 加了 `_UNIFIED_SUBJECT_PROVINCES = {"浙江"}` 短路逻辑——这条改动同样适用于上海，只需把 `"上海"` 加进那个 set。**但这些改动目前是未提交的工作区改动（`git status` 显示 `records.py`/`jobs/collect.py`/`normalizers/common.py` 等多个共享文件被修改），本次任务约定等对方提交后再跟进**，避免两边并发改同一批共享文件冲突。→ 待浙江任务提交后，下一步只是把 `"上海"` 加进 `_UNIFIED_SUBJECT_PROVINCES`，然后就能推进 #1/#2/#3 的发布逻辑，不需要重新设计
2. **东华大学招生计划**：网页端无可采集数据源，需决策改用第三方权威汇总源（如省考试院公布的招生计划本）还是人工从小程序截图录入
3. **上海交通大学招生计划数据是整页图片（报纸排版，31省份列挤在一张图里）—— 已解决**：Vision OCR（`zh-Hans`+`en-US`）识别表头文字会把多个省份名合并成一整段文本、部分列边框被数字遮挡检测不到，靠 OCR 文本或肉眼数列对齐都不可靠（已踩坑：肉眼数列数错过一行）。**改用确定性网格线检测方案**：不依赖 OCR 识别表头文字，而是用像素级"列/行暗像素占比"直接检测表格边框线的精确坐标（真正的边框线在其跨越的整个长度上暗像素占比接近1.0，文字区域则远低于此），从而精确定位出目标省份列（上海）的像素范围；再把"专业名称"列和"上海"列裁剪拼接成两列窄图分段人工核对，彻底消除多列环境下人工数列的风险。抽取结果与图片自带的"总计"行数字完全对账一致（19个专业加总=197，与图片总计行一致），验证了方法可靠。**这个方法已整理成可复用脚本 `backend/scripts/ocr_grid_extract.py`**（`find_grid_lines`网格线检测 + `make_two_column_strip`两列拼接裁剪），未来遇到类似的图片型招生计划数据（其他学校/其他省份）可直接复用，不用重新摸索
4. **复旦大学招生计划 2025/2026 年未公开发布**：WebSearch 多方核实（官网"招生计划"栏目、"招生动态"栏目、第三方汇总），复旦大学官网 `ao.fudan.edu.cn/36332/list.htm` 最新一条是 2024 年（2024-08-30 发布），无 2025/2026 年条目；第三方信息确认"上海具体的分专业招生计划需查阅上海市教育考试院发布的官方招生计划文件"——即复旦大学近两年未把分省分专业计划复刻到自己官网，这与江苏"详细计划是印刷专刊不是网站文件"的已知规律一致。按 PRD"官方未公开则明确标记缺失，不得推算或用旧数据顶替"处理，本轮不采集复旦（不能拿 2024 年数据冒充 2026 年）
5. **上海财经大学验证码 —— 已解决**：验证码是清晰无干扰的4位数字（如"6737"），Playwright 截图后人工肉眼识别一次就填对，无需额外 OCR 工具；已采集完成（见任务#3）

## 执行顺序（Loop Engineering：Discover → Implement → Validate → Publish & Sync）

```
①#0a 数据源审计（可并行：省考试院 + 10校招生网）
  ↓
②#0b 建 shanghai.yaml
  ↓
③#1/#2/#4 省级数据采集（http 自动源，优先跑，无需人工 Playwright）
④#3 招生计划采集（JS 动态渲染校，走 manual + Playwright，逐校推进）
  ↓
⑤ Validate：核对 staging valid/needs_review 比例，异常复用江苏"人工核对原图"模式
  ↓
⑥ Publish（照抄 `publish_jiangsu_*.py` 写 `publish_shanghai_*.py`）
  ↓
⑦ Sync 业务表（复用现成脚本）
  ↓
⑧ #9/#10/#11 按 P1 优先级推进，#11 的 embedding 步骤预期继续卡在 #11 同款外部阻塞
```

## 已知会复用的坑（来自江苏经验，提前预警）

- 各校"招生计划"页大概率是 JS 动态渲染系统，`HttpCollector` 结构性接不了，需要 `collection_method: manual` + Playwright 人工辅助路径
- OCR 依赖 macOS Vision（`scripts/macos_vision_ocr.swift`），Linux 环境跑不了
- RAG chunk 入库和 embedding 生成分两步，`stage_records()` 不自动调 embedding；补 embedding 脚本 `scripts/chunk_documents.py --embed-only` 现成可用，但预期会复现江苏 #11 的 Moonshot 账户权限 403 阻塞
- 专业录取分数线、专业主数据若官方未公开，明确标记缺失，不得推算或用 mock 值补齐

## 快速恢复命令（待 #0a/#0b 完成后补全）

```bash
# 采集（待新建 scripts/run_shanghai_pipeline.py，结构照抄 run_jiangsu_pipeline.py）
.venv/bin/python scripts/run_shanghai_pipeline.py --source <source_id> --raw-root /tmp/shanghai-raw --report-root /tmp/shanghai-reports

# 发布（待新建，照抄江苏对应脚本）
.venv/bin/python scripts/publish_shanghai_admission_scores.py
.venv/bin/python scripts/publish_shanghai_rank_segments.py
.venv/bin/python scripts/publish_shanghai_policy.py
.venv/bin/python scripts/publish_shanghai_admission_plans.py

# 业务表同步（复用现成脚本，province 无关）
.venv/bin/python scripts/sync_published_data_to_business_tables.py
```
