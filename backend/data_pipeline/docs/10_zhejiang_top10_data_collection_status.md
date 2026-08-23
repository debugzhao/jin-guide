# 浙江 Top10 数据采集 — 任务执行状态看板

> 更新时间：2026-08-22 | 参考：`09_pipeline_run_status.md`（江苏看板同构）
> 用途：随时查看每个子任务当前卡在哪一步，快速定位下一步命令，不用重新翻代码
> 白名单口径：艾瑞深校友会网《2025校友会中国大学排名》浙江省内前10（用户已确认，见下方§1），非动态排名结果

## 状态图例

✅ 完成 ｜ ⚠️ 部分完成（有产出但卡在某一步） ｜ ❌ 未开始 ｜ 🛑 阻塞在外部依赖（需人决策/协调） ｜ 🔧 代码适配中（不是数据任务，是"能否复用"的前提） ｜ 🚫 产品决策明确不做（不是遗漏，是主动排除范围）

## §0 数据落地情况（2026-08-22）

之前几轮验证全部跑在 `/tmp` 临时目录，只是验证代码，没有真正落库。现已用
`docker compose exec backend python -m scripts.run_jiangsu_pipeline --config
data_pipeline/configs/zhejiang.yaml --source <id> --persist` 对全部11个http源
重新采集，原始文件落在 `backend/data/raw/浙江/`（6.5M，44个文件），staging数据
写入 `pipeline_staging_records` 表（`--persist`会自动建`pipeline_data_sources`/
`pipeline_collection_runs`记录）。`/tmp`下的浙江相关临时目录已清理。

| source_id | valid | needs_review |
|---|---|---|
| zjzs-policy-2026 / 2025 | 12 / 12 | 1 / 1 |
| zjzs-rank-segment-2026 / 2025 | 428 / 426 | 0 / 0 |
| zjzs-admission-score-2026-stage1 / stage2 | 401 / 2 | 0 / 0 |
| zjzs-admission-score-2025-stage1 / stage2 | 370 / 5 | 0 / 0 |
| nbu-admission-plan-2026 | 90 | 0 |
| zstu-admission-plan-2026 | 61 | 0 |
| hznu-admission-plan-2026 | 42 | 0 |

投档线"第二段"只有2/5条命中白名单10校（已核实不是bug——第二段是征集志愿补缺，
热门院校在第一段就招满了，只有温州医科大学等少数校有零星剩余名额，7239行原始表
里只有这几条属于白名单校）。

### §0.1 发布 + 业务表同步（2026-08-22，追加）

已用 `scripts/publish_zhejiang_data.py --record-type <T> --year <Y>`（新写的通用
发布脚本，浙江这几类记录跟江苏policy/rank_segment一样不需要enrichment就能发布——
投档线原始表本身自带位次，不用像江苏那样另外关联逐分段表）把上述staging全部发布
成不可变 `dataset_version`：

| dataset_version | record_count |
|---|---|
| zhejiang_policy_2026_rank_segment_v1 / 2025 | 428 / 426 |
| zhejiang_policy_2026_policy_v1 / 2025 | 1 / 1（另1条空壳公告页needs_review未发布，同江苏#4模式） |
| zhejiang_top10_2026_admission_v1 / 2025 | 403 / 375（含第一段+第二段合并） |
| zhejiang_top10_2026_plan_v1 | 193 |

再用 `scripts/sync_published_data_to_business_tables.py` 同步进
`enrollment_data_admission_scores`/`rank_segments`/`admission_plans`，三张业务表
最终行数分别是778/854/193，跟发布记录数完全对齐。过程中发现并修复2个连带问题：

1. **`business_sync.py::_UNIVERSITY_META` 没有浙江10校**，会导致同步时全部
   `skipped_missing_university`——已按公开信息（教育部211名单、双一流建设高校
   名单）补全10校的985/211/双一流/学校类型元数据。
2. **`enrollment_data_admission_plans` 的去重键不够细，会把不同专业悄悄合并丢失**：
   浙江单校自采数据没有`major_group`/`major_code`，`subject_type`又恒为`unified`
   （不像江苏能靠物理/历史类区分），首次同步把193条发布记录合并丢成了174条——
   跟`020_admission_plan_major_name`当年修的是完全同一类问题在更深一层重现（那次
   加`major_name`+`subject_type`，这次前提条件变了，两者都不够用）。新增两条迁移
   `024_admission_plan_adm_type`/`025_admission_plan_restrict`分别补`admission_type`
   和`restrictions`两层去重兜底，修复后重新清空重同步，193条一条不丢（含宁波大学
   "水产养殖学"普通类/三位一体两条轨道、"音乐学"器乐/声乐主项两条线，均已验证
   正确保留为独立记录）。

## §1 已确认的10校白名单

| 排名 | 学校 | 教育部代码 | 城市 | 办学性质 | 招生网 |
|---|---|---|---|---|---|
| 1 | 浙江大学 | 10335 | 杭州 | 中央部属(985/211) | zdzsc.zju.edu.cn |
| 2 | 宁波大学 | 11646 | 宁波 | 省属(部省市共建) | zsb.nbu.edu.cn |
| 3 | 浙江工业大学 | 10337 | 杭州 | 省属 | zs.zjut.edu.cn |
| 3 | 浙江师范大学 | 10345 | 金华 | 省属 | zs.zjnu.edu.cn |
| 5 | 西湖大学 | 14626 | 杭州 | **特殊**：教育部批复为"社会力量举办的非营利新型高校"，非central/provincial二值 | zh-ugadmissions.westlake.edu.cn |
| 6 | 浙江理工大学 | 10338 | 杭州 | 省属 | zs.zstu.edu.cn |
| 7 | 浙江工商大学 | 10353 | 杭州 | 省属(省商务部教育部共建) | zhaoban.zjgsu.edu.cn |
| 8 | 杭州电子科技大学 | 10336 | 杭州 | 省属(原电子工业部划转) | zhaosheng.hdu.edu.cn |
| 9 | 杭州师范大学 | 10346 | 杭州 | **注**：杭州市人民政府举办，"省市共建以杭州市管理为主"，行业内通常仍归省属 | undergrad.hznu.edu.cn |
| 10 | 温州医科大学 | 10343 | 温州 | 省属 | zhaosheng.wmu.edu.cn |

已写入 `data_pipeline/configs/zhejiang.yaml`，加载校验通过（`load_pipeline_config` 无异常）。西湖大学 `ownership` 字段留空（`null`），不是缺陷，是如实标记特殊性质。

## §2 与江苏架构的关键差异（影响"复用"边界，必读）

浙江高考不是"物理类/历史类"两科类模式，而是"3+3不分文理"，且志愿单位是"专业(类)+学校"平行志愿，不是江苏的"院校专业组"。这意味着**不能直接照搬江苏解析/发布代码跑一遍**，需要先做§3的代码适配。

## §3 代码适配任务（前提性任务，🔧）

| # | 任务 | 状态 | 说明 |
|---|---|---|---|
| 0a | `records.py` province 硬编码 | ✅ | 5个Record类的 `province: str = "江苏"` 默认值已删除，改为必填字段，倒逼所有构造点显式传入。已修复的调用点：`parsers/tabular.py`（3处）、`parsers/document.py`（2处）、`scripts/publish_jiangsu_admission_plans.py`（1处）、`tests/test_repository.py`+`tests/test_enrichment.py`（4处补`province="江苏"`）+`tests/test_parsing_and_validation.py`（3处补`config=`参数） |
| 0b | `records.py` subject_type 硬编码 | ✅ | `SubjectType` 新增 `"unified"`。同步改了 `normalizers/common.py::normalize_subject_type`（新增`unified`/`不分文理`别名，其余别名待Discover核实浙江官方原文用词后再补）和 `jobs/collect.py::_infer_subject`（改为实例方法，`_UNIFIED_SUBJECT_PROVINCES={"浙江"}`命中时直接短路返回`unified`，不再依赖标题里的"物理/历史"关键词） |
| 0c | `loaders/repository.py:183` dataset名称硬编码前缀 | ✅ | 新增 `_PROVINCE_SLUGS`（`{"江苏": "jiangsu", "浙江": "zhejiang"}`）+`_province_slug()`，未注册的省份直接抛`PublicationError`而不是编造一个拼音写法。江苏原有 `jiangsu_top10_2025_admission_v1` 命名不变（`test_repository.py:104`断言仍通过） |
| 0d | `parsers/document.py::extract_policy_rule` 正则硬编码 | ✅ | `max_volunteers` 正则新增匹配 `专业(类)+学校`/`专业类+学校`/`专业+学校` 分支（与原有`院校专业组`并列），具体是否命中还要等Discover阶段拿到真实浙江政策原文才能验证——当前只是让正则"有能力"匹配，未用真实文本验证过 |
| 0e | 下游消费层（超出本次采集任务范围，仅记录不处理） | 🛑 | `app/agent/nodes/data_resolver.py:50`、`app/api/v1/reports.py:283` 用 `"physics" if "物理" in subjects else "history"` 二元推断科类，浙江学生选科不会含"物理"字面值会被误判成"history"；`app/api/v1/risk.py` 的批次线字典也是二值。**这是"让浙江考生用上系统"这个更大产品需求的范围，不是本次数据采集任务范围**，此处仅标记已知限制，不在本次任务内解决 |

全量测试验证：`.venv/bin/pytest -q` 258 passed（在原258基础上无新增用例，本轮只是修复现有断言的调用签名，未新增测试——Discover阶段有真实浙江数据后应补浙江专属用例）。

## §4 数据任务看板

| # | 任务 | 状态 | 产出 / 卡点 / 下一步 |
|---|---|---|---|
| 1 | 2025/2026 平行投档分数线（`admission_score`） | ✅ | **已用真实数据跑通并验证**：新写`parse_zhejiang_admission_score_rows`（扁平表专用，复用`major_group_code`/`major_group_name`存专业代号/名称，直接读位次不需要enrichment），`--source zjzs-admission-score-2026-stage1`真实拉取xls解析出401条，401条全部`valid`、0条`needs_review`/`rejected`。抽样核对`university_code`按教育部标准代码正确映射（浙大10335等）、`provincial_university_code`存浙江本地代号（如浙大"0001"）、`batch="第一段"`（从标题"第一段"关键词判断）、`subject_type=unified`全部正确。**白名单10校里9校有数据，西湖大学0条**——已用真实xls核实确认这不是匹配bug，是西湖大学本身不参与这份标准普通类平行录取批次（其招生规模极小，走的是"创新班"等特殊渠道，数据在招生简章正文里，不在这类结构化表格中，属于真实缺失，如实标记不推算） |
| 2 | 2025/2026 总分分数段表（`rank_segment`） | ✅ | **已用真实数据跑通并验证**：`--source zjzs-rank-segment-2026`拉取官方PDF，OCR/表格解析出428条，428条全部`valid`、0条`needs_review`/`rejected`，抽样核对分数从693到266递减、位次同步递增、`province=浙江`、`subject_type=unified`全部正确，字段完全符合预期。当前只是staging，未跑publish |
| 3 | 2026 招生计划（10校，`admission_plan`） | ⚠️ | **5校已用真实数据跑通**：新写`parse_single_university_admission_plan_rows`（单校专属页解析，不依赖"院校名称"列匹配白名单，因为target_university_code已经知道是哪一所）——宁波大学90条valid、浙江理工大学61条valid、杭州师范大学42条valid，共193条全部`valid`、0条`needs_review`/`rejected`。浙江工业大学确认真实内容需要JS渲染（`#news1content`静态HTML里是空的，已用真实响应验证），改成`collection_method: manual`；浙江工商大学本来就是manual（JS查询页）。**5校未登记**：浙大/西湖大学官网无承载页；杭电未定位到2025/2026年具体条目；温州医科大学数据在微信公众号文章里，共2/10走manual、5/10走http全部跑通、3/10缺口 |
| 4 | 2025/2026 招生政策（`policy`） | ✅ | **已用真实数据跑通并验证**：`--source zjzs-policy-2026`真实拉取通知页+docx附件（zjzs.net的附件是`downfile.jsp?...&filename=x.docx`下载代理端点，不是直链，过程中发现并修复了3个连带bug，见下方"Implement阶段发现的新问题"），docx正文提取出11条`DocumentChunkRecord`（内容可读、非乱码）+ 1条`valid`的`PolicyRuleRecord`（`volunteer_mode=parallel`, `max_volunteers=80`，已用真实政策原文验证准确）+ 1条`needs_review`（来自入口公告页本身，同江苏#4"空壳公告页"模式） |
| 5-8 | 2023/2024 分数线+分数段表 | 🚫 | **产品决策：明确不做**（2026-08-23），不再是"未排期"而是主动排除范围，理由不变（浙江3+3推行时间线与格式存在不确定性，投入产出比低于其他任务） |
| 9 | 10校专业录取线 | ⚠️ | 10校里只2所（浙师大/杭师大）确认有省考试院表之外的补充信息（均分/最高分/实际录取人数），已用杭州师范大学2025年真实数据跑通46条valid；其余8校见下方"2026-08-23 追加"小节逐校结论 |
| 10 | 院校/学院/专业主数据 | ❌ | 未登记数据源，且浙江"专业(类)+学校"模式下专业主数据的粒度需要重新设计 |
| 11a | 10校章程/专业介绍（RAG） | ✅ | 章程7校（浙大/宁波/浙工大/浙师大/浙理工/温医/杭师大）+ 专业介绍5校（浙大/宁波/浙工大/浙理工/浙工商）已用真实数据跑通，共807条`DocumentChunkRecord` valid，847个rag_chunks全部embedding完成（DashScope 1024维，见下方"2026-08-23 追加"小节）；西湖/工商/杭电章程和杭电/温医专业介绍因JS渲染/无统一列表页暂缺，浙师大/杭师大专业介绍因托管在微信公众号被反爬拦截未查实 |
| 11b | 转专业政策（RAG） | 🚫 | **产品决策：明确不做**（2026-08-23） |
| 12 | 教育部院校/专业标准目录 | ⚠️ | 见下方"2026-08-23 追加"小节——之前"可与江苏共用"这句结论未经核实，正在重新核查 |
| 13 | 业务表同步 loader | ✅ | 已完成，见§0.1（`enrollment_data_admission_scores`/`rank_segments`/`admission_plans`分别778/854/193行，跟发布记录数完全对齐） |

### 2026-08-23 追加：#9 10校专业录取线 —— 逐校核实结果

省考试院投档线表（任务#1，已完成）只有分数线+位次，PRD要求"官方提供时保存平均分、
最高分和录取人数"这类补充字段，只有学校自己发布的"历年录取情况"页才可能有。逐校
核实结果：

| 学校 | 结论 | 说明 |
|---|---|---|
| 杭州师范大学 | ✅ 已采集，46条valid | 新写`parse_single_university_admission_result_rows`，`hznu-major-admission-result-2025`源，真实表头"专业名称/录取数/最高分/最低分/平均分/最低位次"，是2025年最新数据 |
| 浙江师范大学 | 🛑 曾有，已迁移到JS单页应用 | 官网"往年录取分数"栏目已从静态HTML文章（2017-2023年，`zs.zjnu.edu.cn`域名下）迁移到`lqcx.zjnu.edu.cn/zsdata/lqxx/#/lnfs`纯JS前端应用，httpx拿不到数据，需要浏览器渲染或找后端API，本轮未做 |
| 浙江理工大学 | ⚠️ 部分命中，未采集 | "历年录取"栏目有独立页面（如`zs.zstu.edu.cn/info/1038/3746.htm`），有平均分但没有录取人数字段，且核实到的最新是2023年（非2025/2026），价值低于杭师大，本轮未采集 |
| 杭州电子科技大学 | 🚫 判定无需额外采集 | 页面明确注明"表中数据为各省各专业首轮投档录取分"，本质就是投档线，跟任务#1数据重复 |
| 浙江大学、浙江工业大学（近年） | 🚫 判定无需额外采集 | 栏目名叫"历年分数"，但内容已退化成省份/科类投档线汇总，跟任务#1数据重复（浙工大2016年有过带均分/人数的完整表，但年份太旧无实用价值） |
| 宁波大学、浙江工商大学 | ❓ 未查实 | 疑似入口需要考生个人信息/验证码查询，或AJAX动态渲染，静态抓取拿不到内容，需要浏览器自动化才能确认 |
| 西湖大学 | ❓ 未查实 | 官网无历年统计栏目，公开分数线均来自第三方汇总站，权威性不足不采信 |
| 温州医科大学 | ❓ 未查实 | 疑似有对应页面（搜索结果标题命中"三位一体招生录取情况统计表"），但两次WebFetch均404，可能是页面已改版失效或需要动态加载，需要人工用浏览器打开确认 |

**这条数据目前只staging，没有publish**：`major_group_code`复用专业名称（这份数据源没有专业代号），跟省考试院表的数字代号在取值格式上不同，natural_key不会跟已发布的admission数据集冲突，但两者是同一个真实世界事实的两份不完全重叠的记录，要不要合并需要产品决定，本轮不擅自处理。

### 2026-08-23 追加：#11a 10校章程/专业介绍 —— 采集结果

RAG之前卡在Moonshot embedding账户权限（`09_pipeline_run_status.md`#11），**这个阻塞已经解决**——另一个并行会话把embedding模型切换到了DashScope（1024维），已实测验证真实可用（`embed_text`调用成功返回1024维向量，检索到的浙大章程"调剂规则"段落语义相关度合理，cosine距离0.208）。

| 类型 | 覆盖学校 | 结果 |
|---|---|---|
| 招生章程 | 浙大(2025)/宁波/浙工大/浙师大/浙理工/温医/杭师大，共7校 | 21条`DocumentChunkRecord` valid，内容为真实录取规则/学费/单独招生条款正文 |
| 专业介绍 | 浙大/宁波/浙工大/浙理工/浙工商，共5校 | 786条`DocumentChunkRecord` valid（用discovery自动发现列表页下的各专业/学院子页） |

**缺口（本轮未做，需要额外工程）**：
- 章程：西湖大学、浙江工商大学、杭州电子科技大学——正文由前端JS异步加载，纯HTTP拿不到，需要浏览器渲染或用教育在线镜像页（`zhejiang.eol.cn`）交叉验证兜底
- 专业介绍：杭州电子科技大学、温州医科大学——没有统一列表页，专业介绍分散在各学院子站，需要先枚举学院列表再逐个采集；浙江师范大学、杭州师范大学——专业介绍正文实际托管在微信公众号，WebFetch访问会触发反爬验证墙，需要人工或专门的微信文章抓取方案

**踩到的坑（已修复，用真实数据验证过）**：
- 章程页忘了设`discovery_depth: 0`（跟之前nbu-admission-plan-2026同一个坑），默认depth=1把整站导航当成"可能的附件"抓了一遍（21-31个artifact/次，22条parsed_records其实大部分是导航栏目的噪音），删掉重跑后每校正确收敛到1个artifact
- `_read_html_table`原来只处理页面第一个`<table>`，遇到杭州师范大学"历年招生-录取情况"这种页面（导航栏用`<table>`布局、且嵌套子表格）会把装饰性表格误当成数据表、或被嵌套表格提前触发"表格结束"把真正数据表截断。改成按嵌套深度过滤（只收集深度恰好为1、不嵌套在别的表格里的顶层表格），并在多个顶层表格里挑行数最多的当数据表——已用杭州师范大学2025年录取情况页（47行数据表+5个装饰表格混在一起）验证过

### 2026-08-23 追加：#12 教育部院校/专业标准目录 —— 核实结果

用户指出"可与江苏共用同一份目录"这句结论此前未经核实，已用WebSearch/WebFetch重新核查：

- **"全国统一、不分省份"这个判断本身是对的**：教育部官网（moe.gov.cn）和阳光高考同步发布同一份《全国高等学校名单》，全国唯一一份，不因省份变化。专业目录同理。
- **但"可与江苏共用"这句话的隐含语气是误导的**：它容易让人以为"江苏那边已经采集好了，直接拿来用就行"，事实是**江苏这项任务同样是❌未采集**（`09_pipeline_run_status.md`#12 状态也是❌，`08_jiangsu_data_pipeline_handoff.md`只把它列为遗留任务）。准确的说法应该是"两省共享同一个尚未完成的任务，不是现成可复用的数据"。
- **两份数据的真实官方来源已核实**：
  - 院校名单：`http://www.moe.gov.cn/jyb_xxgk/s5743/s5744/202506/t20250627_1195683.html`（2025-06-27发布，全国2919所普通高校=本科1365+专科1554，附件`xls`格式，已curl验证200）
  - 专业目录：`http://www.moe.gov.cn/srcsite/A08/moe_1034/s4930/202504/t20250422_1188239.html`（**不是2024年版，是2025年4月发布的《普通高等学校本科专业目录（2025年）》**，93个专业类845种专业代码，附件是`PDF`表格，比院校名单的xls解析成本更高）
- **这不是几行配置能解决的**：`config.py::DataType`里已经预留了`university_master`/`major_master`两个值，但`records.py`还没有对应的Record类，`jobs/collect.py::_parse_node`也没有这两个data_type的解析分支（命中会直接落到"parser not implemented"），且PDF专业目录表格解析、以及院校/学院/专业主数据建表（任务#10）本身就是一块新工作，不是"江苏浙江各registerm一下source就完事"的量级。**建议单独作为一个不分省份的任务处理**（比如`configs/national.yaml`），不合并进浙江或江苏各自的yaml——已跟用户确认范围后再动手，本轮只完成核实，未开始实现。

### Implement 阶段已发现并修复的问题（用真实线上数据验证过，非假设）

- **policy 附件是 docx 不是 pdf**：新增 `extract_document_text` 的 `.docx` 解析分支（`python-docx`，已加入`requirements.txt`），按文档原始顺序读段落+表格。已用真实2026年浙江政策docx验证提取效果正常（非乱码）。
- **zjzs.net 附件是下载代理端点，不是直链**：附件真实URL是`/module/download/downfile.jsp?...&filename=x.docx`，扩展名藏在query参数里，不在URL路径里。修了两处：`discovery.py::discover_links`（原来只查`parsed.path`的后缀，现在也查query参数值）和`raw_store.py::_safe_suffix`（同理，且发现这个下载端点的`Content-Type`响应头被服务器错误标成`text/html`——**如果不查query参数会把docx文件误存成`.html`再被当成HTML乱码解析**，已用真实响应头验证过这个坏case确实会发生）。
- **`extract_policy_rule`的`max_volunteers`正则**：浙江政策原文实际用词是"专业平行志愿"+"考生每次可填报不超过80个志愿"（不是笔者最初猜测的"专业(类)+学校"），且同一份文档里还有"传统志愿"轨道下不相关的"5个院校志愿""6个专业志愿"两个干扰数字，第一版正则曾误抓到"1个志愿"（来自"1个志愿单位"这句说明性文字）。最终用`不超过(\d{1,3})个志愿(?!单位|专业|院校)`精确锁定，已用真实文档验证提取出正确的`80`，并补了两条回归测试（`test_parsing_and_validation.py`，江苏用例+浙江用例各一条）覆盖这个坑。
- **`run_jiangsu_pipeline.py`硬编码只认`jiangsu.yaml`**：脚本本身跟省份无关，加了`--config`参数（默认仍指向jiangsu.yaml不破坏现有文档里记录的命令），本次浙江所有真实数据验证都是用这个脚本跑的。
- **admission_score新写`parse_zhejiang_admission_score_rows`**（`data_pipeline/parsers/tabular.py`）：浙江扁平表结构（学校代号/学校名称/专业代号/专业名称/计划数/分数线/位次）跟江苏合并单元格格式完全不同，新写专用函数而不是改`parse_admission_score_rows`的别名（避免把江苏那份搞复杂）；`jobs/collect.py`按`config.province`分派到对应解析函数，并新增`_infer_zhejiang_stage`从标题识别"第一段/第二段"写入`batch`字段。已用真实2026年第一段xls验证：401条全部valid。
- **HTML编码不能假设UTF-8**：杭州师范大学页面是GB2312编码，统一当UTF-8解码会把中文标题读成乱码（`errors="replace"`不报错，只是静默产出垃圾），导致discovery标题匹配和正文提取全部静默失效。新增`data_pipeline/text_encoding.py::decode_html_bytes`（从HTML头部`charset`声明识别真实编码，读不到才回退UTF-8），`jobs/collect.py`/`document.py`/`tabular.py`三处读HTML字节的地方全部切过去。
- **单校招生计划页需要新解析路径**：`read_tabular_document`新增`.html`/`.htm`支持（`_read_html_table`，正确处理`rowspan`/`colspan`合并单元格，续格填空字符串跟openpyxl语义一致）；新写`parse_single_university_admission_plan_rows`——不像省级汇总表那样按"院校名称"列匹配白名单，因为`target_university_code`已经知道是哪一所学校，改用关键词包含匹配识别列头（各校写法差异大："专业（类）名称" vs "专业名称"）。已用宁波大学/浙江理工大学/杭州师范大学三所真实数据验证。
- **AdmissionPlanRecord的natural_key太粗，同一专业名称的不同招生线会被误判重复**：真实数据里发现两类坑——①宁波大学"水产养殖学（拔尖人才创新班）"在"普通类"平行志愿和"三位一体"综合评价两条轨道各出现一次，仅靠`admission_type`默认值分不开；②浙江理工大学"电子信息工程(电力电子技术)(本科)"在"单独考试招生计算机类"/"单独考试招生电子与电工类"两条线各出现一次，连`restrictions`都完全相同。修法：`validators/quality.py::natural_key`把`restrictions`也纳入去重key；解析函数里"类别"列不匹配标准"普通类 0005"格式时，退化成用原始类别文本兜底当`admission_type`；新增识别"批次"列（浙江理工大学表头真的叫"批次"），值存在时优先用它而不是函数默认的"本科批"。
- **discovery_title_pattern 按学校名称本身命中会引入其他省份的数据**：浙江理工大学网站上每个省份的分省计划链接都是"浙江理工大学2026年分省招生计划（XX省）"，之前只写`discovery_title_pattern: 浙江`会把全部18个省份的链接都匹配上（因为学校名字本身带"浙江"两个字），而不仅仅是目标省份——已用真实页面验证到这个坑（部分专业曾同时收到"浙江"和其他省份的计划数据，被误判成同一个natural_key下的"重复"）。改成精确锁定`分省招生计划（浙江）`这个带括号的完整短语才安全。
- **JS重定向壳/JS异步渲染无法用纯HTTP采集**：浙江工业大学列表页链接指向的是一个JS重定向壳（`top.window.location=...`），httpx不执行JS只能拿到935字节的空壳；跟进真实文章页后确认数据容器`#news1content`是空的（内容由前端异步渲染），已用真实响应验证过，改成`collection_method: manual`走Playwright人工辅助路径，不再当成http源硬跑。

### 已知会卡住的坑（尚未处理）

- **西湖大学不在标准投档线表里**：9/10白名单校在admission_score真实数据里有记录，西湖大学0条——已核实不是解析bug，是它招生规模极小、走"创新班"等特殊渠道，数据只存在于招生简章正文，不在这类结构化文件里。发布/展示时不能对西湖大学的admission_score留白，要明确标"不适用"而不是"未采集"。
- **10校招生计划最终覆盖率7/10**（http直采5校+manual标记2校，缺口3校：浙大/西湖大学无承载页，杭电未定位到具体年份条目，温州医科大学数据在微信公众号文章里），低于江苏10/10，需要跟你对齐验收线。

## §5 推荐执行顺序

```
①#0a-0d 代码适配（阻塞一切浙江数据正确落库，工作量S）                         ✅ 已完成 2026-08-22
②省级source Discover+登记（policy/rank_segment/admission_score共8条 + 5校admission_plan） ✅ 已完成 2026-08-22
③#4 policy 端到端跑通验证（docx解析+zjzs.net下载代理端点+policy正则三个连带bug）     ✅ 已完成 2026-08-22
④#2 rank_segment 端到端跑通验证（428条valid，0 needs_review/rejected）           ✅ 已完成 2026-08-22
⑤#1 admission_score 端到端跑通验证（新写浙江专用解析函数，401条valid）             ✅ 已完成 2026-08-22
⑥#3 10校招生计划：5校http直采跑通（193条全部valid）+2校标记manual                 ✅ 已完成 2026-08-22（7/10，见下方坑记录）
⑦#5-8/#11b 产品决策明确不做（2023/2024历史数据、转专业政策）                    ✅ 已确认 2026-08-23
⑧#13 业务表同步 loader                                                    ✅ 已完成 2026-08-22（见§0.1）
⑨#11a RAG章程+专业介绍：Moonshot权限阻塞已解决（切DashScope），7校章程+5校专业介绍
   跑通（807条valid，847个chunk全部embedding完成）                          ✅ 已完成 2026-08-23
⑩#9 10校专业录取线：杭州师范大学46条valid跑通，其余9校逐校核实结论见上文         ✅ 已完成 2026-08-23
⑪#12 教育部院校/专业标准目录：核实清楚真实来源和工作量，未开始实现               ⚠️ 已完成 2026-08-23（核实）
⑫#10 院校/学院/专业主数据                                                 ← 下一步（未开始）
```

## 补充说明

- ~~浙江`major_group_code`字段怎么填~~ 已解决：`parse_zhejiang_admission_score_rows`复用`major_group_code`/`major_group_name`存专业代号/专业名称，理由是浙江"1个专业(类)"和江苏"1个院校专业组"同为最小志愿单位，语义对得上
- 西湖大学的 `ownership` 无法用现有 `central`/`provincial` 二值描述，已在yaml里留空，后续如果要在其他代码里按ownership分组统计需要注意这条记录会被漏统计
- RAG embedding 阻塞是全局性的（Moonshot账户权限），不是浙江任务新引入的问题，见`09_pipeline_run_status.md`#11
