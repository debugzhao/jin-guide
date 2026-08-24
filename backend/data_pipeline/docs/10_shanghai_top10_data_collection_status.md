# 上海 Top10 数据采集 — 任务执行状态看板

> 创建时间：2026-08-22 | 复用江苏 pipeline 架构（`data_pipeline/`），架构/代码不重新发明，只新增 `configs/shanghai.yaml` + `scripts/*_shanghai_*.py`
> 目标高校（已与产品侧确认，4所985+5所211+1所行业强校）：
> 复旦大学、上海交通大学、同济大学、华东师范大学、上海财经大学、上海外国语大学、华东理工大学、东华大学、上海大学、上海理工大学
> 用途：随时查看每个任务当前卡在哪一步，快速定位下一步命令，不用重新翻代码。参考江苏看板：`09_pipeline_run_status.md`

## 状态图例

✅ 完成（已发布+已同步业务表） ｜ ⚠️ 部分完成（有产出但卡在某一步） ｜ 🔄 进行中 ｜ ❌ 未开始（无数据/无表结构） ｜ 🛑 阻塞在外部依赖（非代码问题，需要人决策/协调） ｜ 🚫 产品侧已确认不做（非遗漏）

## 任务看板

| # | 任务 | 状态 | 产出 | 卡点 / 下一步 |
|---|---|---|---|---|
| 0a | 数据源审计（上海市教育考试院官网 `shmeea.edu.cn` + 10校招生网） | ✅ | 见下方「Discover 阶段结论」 | 无 |
| 0b | 建 `configs/shanghai.yaml` | ✅ | 已建，10校+14个source，`load_pipeline_config` 校验通过 | 无。东华源已注册但 `enabled: false`（架构性阻塞，见#3） |
| 1 | 2025 投档线（`admission_score`） | ✅ | 28条valid（9+7条580分以上未公开已如实跳过）→ 已发布`shanghai_top10_2025_admission_v3`→ 已同步`enrollment_data_admission_scores`（28条，含min_rank） | 无 |
| 2 | 2025 逐分段表（`rank_segment`） | ✅ | 212条valid（复用`parse_rank_segment_rows`，扫描版PDF走新增的Vision OCR回退路径）→ 已发布`shanghai_policy_2025_rank_segment_v1`→ 已同步 | 无。入口页另外11份艺术类/体育类专业统考分布表已排除在`discovery_title_pattern`之外（详见下方"需要决策"） |
| 3 | 2026 招生计划（10校，`admission_plan`） | ✅ | **8/10校**已采集+发布：华东师范大学(41)、上海外国语大学(23)、同济大学(13)、华东理工大学(35)、上海大学(36)、上海理工大学(20)、上海财经大学(25)、上海交通大学(19，报纸版式图片+网格线检测)，合计212条valid→已发布`shanghai_top10_2026_plan_v2`→已同步`enrollment_data_admission_plans`（210条，2条因admission_type未入去重键与同名记录合并，可接受） | 复旦大学：官网2025/2026年未公开发布（非采集问题，见下）；东华大学 🛑：官网明确写数据仅在微信小程序内查询，需产品侧决策替代方案 |
| 4 | 2025 招生政策（`policy`） | ✅ | 1条valid（本科普通批次样表，max_volunteers=24）→已发布`shanghai_policy_2025_policy_v1`→ 已同步（PolicyRuleRecord目前无business_sync同步逻辑，与江苏#4遗留问题相同） | 2条"综合评价批次"/"零志愿批次等"样表因超出本轮"本科普通批次"范围已显式rejected（不是编造修正，见发布脚本注释） |
| 5 | 2023 投档线 | 🚫 | 无 | **产品侧已确认不做**（2026-08-23），非遗漏 |
| 6 | 2023 逐分段表 | 🚫 | 无 | **产品侧已确认不做**（2026-08-23），非遗漏 |
| 7 | 2024 投档线 | 🚫 | 无 | **产品侧已确认不做**（2026-08-23），非遗漏 |
| 8 | 2024 逐分段表 | 🚫 | 无 | **产品侧已确认不做**（2026-08-23），非遗漏 |
| 9 | 10校专业录取线 | ❌ | 无 | 未开始原因：本轮时间优先级放在了#1-#4的省级数据+8校招生计划上，没有遗漏也没有技术阻塞——需要逐校排查官网是否公开"专业录取分数线"（区别于已采集的院校专业组投档线），未公开则明确标记缺失，不推算。工作量预估与#3（8校招生计划）同量级 |
| 10 | 院校/学院/专业主数据 | ⚠️ | 院校层：`enrollment_data_universities`已补全7所(华东理工/上海理工/东华/华东师大/上外/上海财大/上海大学)的`is_985`/`is_211`/`is_shuangyiliu`/`school_type`元数据（`business_sync.py::_UNIVERSITY_META`），复旦/交大/同济此前已存在 | 学院/专业层仍无实体表（同江苏#10现状） |
| 11 | 10校章程/专业介绍（RAG） | ✅ | **章程8/10校**、**专业介绍6/10校**（华师大单页+财大/上外/东华/华东理工/上海大学6个大类子站）已全部采集+chunk+embed完成，且已过语义检索抽测验证（2026-08-24，5条覆盖章程条款+专业介绍的真实提问，top-1/top-2均命中对应学校正确文档，如"东华纺织学院专业方向"→纺织学院正文、"上大钱伟长学院"→学院介绍原文）。`rag_documents`按`source_url`域名过滤出的上海8所章程数据抽查干净，无导航栏垃圾页混入 | 复旦、交大：章程未本地托管/反爬412、JS渲染SPA，均未采集；同济：Playwright渲染确认"专业介绍"栏目实际只是历年专业名录一览表、无介绍性正文，跟复旦/交大一样归为无实质内容；上海理工：专业介绍列表页多数条目外链微信公众号，采集可行性存疑，未采集。**转专业政策已明确不做**（2026-08-23），范围收窄为只做章程+专业介绍两类。**上海财经大学"经济学拔尖班/金融实验班"等几个专业介绍页正文极薄**（实测只有一行"实验班介绍：跳转微信公众号链接"，无实质文字），是官网结构限制，不是采集bug，暂不处理 |
| 12 | 业务表同步 | ✅ | `scripts/sync_published_data_to_business_tables.py` 已跑，#1#2#3#4全部同步，`skipped_missing_university`清零 | 无 |

## Discover 阶段结论（2026-08-22，WebSearch/WebFetch 实测，未编造URL）

### 省级数据源（上海市教育考试院 `www.shmeea.edu.cn`）

| 数据类型 | 结论 |
|---|---|
| 逐分段表 | 名字叫《成绩分布表》但结构其实和江苏逐分段表一样（分数/人数/累计人数三列，逐分不逐段），可直接复用`parse_rank_segment_rows`；入口页`page/09000/20250623/19549.html`下还链接着11份艺术类/体育类专业统考考生的同结构分布表，**这些是不同报考人群，不能和全体考生的分布表混在同一个`(province,year,subject_type,score)` natural_key空间**，`discovery_title_pattern`已收窄为只匹配全体考生表，避免自然键冲突（实测踩过这个坑） |
| 投档线 | 只找到PDF直链（`download/20250719/186.pdf`普通批次、`185.pdf`Q组中外合作），未找到承载下载链接的公告母页面，entry_url直接指向PDF文件（HttpCollector对非.html不会走discover_links，可以直接下载解析）；本科普通批次是"院校专业组"平行志愿，不分物理/历史；**580分及以上考生分数线官方不公开**（"由市教育考试院会同考生所在中学逐一告知"），解析器遇到"XXX分及以上"字样会跳过而不是把580当真实投档线（曾经手滑用`_integer()`直接从"580分及以上"里提取出580，已修复） |
| 招生政策 | `page/06300/20250425/19280.html`，页面本身即政策全文HTML（非入口页+附件模式），可直接复用`policy_document_v1`；同一入口下的10个PDF附件其实是不同批次的"考生志愿表样表"（综合评价批次/零志愿批次+提前批+专项/艺体类/**本科普通批次**/专科等），只有"表4-本科普通批次"这份在本轮范围内，其余按超出范围处理 |

### 10校招生计划页

| 学校 | 代码 | 结论 |
|---|---|---|
| 复旦大学 | 10246 | 静态HTML，但数据是PNG图片非文本表格；列表页最新只到2024年，**2025/2026年官方未公开发布**（WebSearch多方核实确认，非采集能力问题） |
| 上海交通大学 | 10248 | 报纸版式整页图片（31省份列一张图），用像素级网格线检测+人工视觉核对成功采集，见下方方案说明 |
| 同济大学 | 10247 | JS动态查询系统，页面默认已定位到上海，直接读取渲染表格 |
| 华东师范大学 | 10269 | JS动态AJAX模板渲染，与江苏南大同一套模板系统 |
| 上海财经大学 | 10272 | JS动态查询系统，带4位数字图片验证码，截图后人工识别一次成功 |
| 上海外国语大学 | 10271 | 同华师大同模板系统 |
| 华东理工大学 | 10251 | Vue SPA，纯前端渲染 |
| 东华大学 | 10255 | 🛑 官网公告明确写"计划数据仅在微信小程序内查询"，网页端无查询系统无PDF，Playwright无法处理小程序 |
| 上海大学 | 10280 | JS动态（ASP.NET+AJAX grid） |
| 上海理工大学 | 10252 | JS动态（四级下拉+查询按钮）；该校查询系统不提供逐专业选考科目字段 |

### 10校章程/专业介绍页——三个特殊情况（2026-08-23）

这三所在RAG采集范围里比较特殊，不是"还没做"，是本轮排查后确认**没有可用的正文数据源**：

| 学校 | 情况 | 结论 |
|---|---|---|
| 复旦大学 | 章程未本地托管（招生网条目本身外链跳转到教育部阳光高考平台，直接抓取返回`412 Precondition Failed`反爬）；专业介绍栏目"院系介绍"实际是跳到主站`www.fudan.edu.cn`的各学院官网导航列表，不是招生向的专业介绍文章 | 章程+专业介绍**都没有可采集的正文来源** |
| 上海交通大学 | 章程页面`admissions.sjtu.edu.cn`是JS渲染SPA，静态抓取只能拿到页面外壳（联系方式），拿不到正文；专业介绍栏目"招生专业"实际是历年"本科招生专业一览表"（名录/PDF），只有强基计划专业有独立培养方案文章，普通专业没有介绍正文 | 章程+专业介绍**都没有可采集的正文来源** |
| 同济大学 | 用Playwright渲染`bkzs.tongji.edu.cn/major/index`后确认，"招生专业"栏目实际内容是2019-2026年逐年的"招生专业（类）一览表"（专业名录列表），不是介绍性文字——跟最初判断的"列表页链多篇文章"不一样，这个栏目本身就没有可用于RAG的内容 | 专业介绍**没有可采集的正文来源**（章程本身走信息公开网`xxgk.tongji.edu.cn`已采集成功，不受影响） |
| 上海理工大学 | 专业介绍列表页`zhaoban.usst.edu.cn/16002/list.htm`先分"按大类""按专业"，多数专业条目直接外链`mp.weixin.qq.com`微信公众号文章（部分用站内`_redirect`跳转），只有少数是站内二级列表页 | 采集可行性存疑，**本轮未采集**，需要评估微信公众号文章的可访问性/反爬策略 |

## 关键技术方案沉淀

1. **`SubjectType` schema 已解决（由并行的浙江任务打好基础，上海在此之上补province分支）**：`records.py::SubjectType`现为`Literal["physics","history","unified"]`，`jobs/collect.py::_UNIFIED_SUBJECT_PROVINCES = {"浙江","上海"}`。上海的投档线/逐分段表/招生计划语义与浙江不同（院校专业组结构、580分不公开、无第一段第二段概念），因此`admission_score`的省份分支从"进了unified集合就走浙江解析器"改成显式按`province=="浙江"`/`province=="上海"`分别调用各自的解析函数，不能共用同一条判断逻辑。
2. **上海投档线解析器 `parse_shmeea_admission_score_rows`**（`data_pipeline/parsers/tabular.py`）：按`院校专业组代码`+`院校专业组名称`（简称如"上海交大"需要显式别名表`_SHMEEA_UNIVERSITY_ALIASES`映射到教育部标准代码，已用真实PDF核对全部10校写法）+`投档线`列解析；`major_group_name`必须保留"(01)"这类组别后缀（不能只存学校简称），否则`business_sync.py::sync_admission_scores`按`major_category`去重时会把同校多个专业组的分数互相覆盖（实测踩过：华东理工两个专业组560/548分先被合并成一条）。
3. **扫描版PDF的OCR兜底**（`parsers/tabular.py::_read_pdf_via_ocr`）：`_read_pdf`原来遇到无可提取文本/表格的PDF直接报错要求人工，现改为自动渲染成图片后走跟`_read_image`一样的macOS Vision OCR路径（仅限本地macOS开发环境，Linux/生产环境仍需PaddleOCR），上海《成绩分布表》PDF没有文字层就是靠这条路径解析成功的。
4. **上海交大招生计划图片（报纸排版，31省份列一张图）**：不依赖OCR识别表头文字（会把多个省份名合并成乱码），改用像素级"列/行暗像素占比"检测表格边框线精确坐标（真实边框线在跨越的整条长度上接近100%暗，文字区域远达不到），定位出目标省份列的像素范围后，把"专业名称"列和目标列裁剪拼接成两列窄图人工核对，避免多列环境数错列。抽取结果与图片自带"总计"行（197）完全对账一致。方法固化为`backend/scripts/ocr_grid_extract.py`（`find_grid_lines`+`make_two_column_strip`），可复用于其他学校/省份的图片型数据。
5. **政策PDF的"样表"陷阱**：`extract_policy_rule()`给`batch`字段的默认值是常量"普通类本科批"，不会根据文档实际内容判断——上海政策入口下10个PDF附件是不同批次的"志愿表样表"，若不加区分直接发布，会把"综合评价批次"的max_volunteers=4误标成"本科普通批次"。发布脚本按`provenance.source_title`精确匹配，只保留"表4-本科普通批次"那份，其余显式`rejected`并注明原因，不做批次归属的猜测性修正。
6. **院校主数据缺口会导致同步静默跳过**：`business_sync.py::_UNIVERSITY_META`是一个按学校代码手动维护的白名单字典，不在其中的学校即使投档线/招生计划已发布，`sync_*`也会把它们计入`skipped_missing_university`而不报错——本轮已为7所上海高校补齐该字典项（复旦/交大/同济此前已在`enrollment_data_universities`表中，不需要补）。
7. **RAG章程数据源踩过一次严重污染事故，已修复**：`SourceConfig.discovery_depth`默认值是1，注册章程/专业介绍这类"单页自包含文档"的source时如果没显式写`discovery_depth: 0`，会把入口页上**所有**链接（包括导航栏"保送生""强基计划""综合评价录取""转专业""辅修""联系我们"等跟章程内容毫无关系的站内链接）当成depth-1附件抓下来，逐个chunk成`document_type=charter`写进`rag_chunks`——检索时会返回大量不相关内容。已发现（华师大一个源就混入了34个无关文档、64条chunk）并清理干净（连带删除了受污染的`rag_documents`/`rag_chunks`/`pipeline_staging_records`/`pipeline_source_documents`共计上千行），9个章程/专业介绍source全部显式补上`discovery_depth: 0`后重新采集，现在每个source只有1个artifact，干净。**结论：注册"单文档"类型的source时必须显式设置`discovery_depth: 0`，不能依赖默认值。**
8. **`app/engine/embedding.py::_BATCH_SIZE`超过DashScope单次请求上限**：切换到DashScope `qwen3.7-text-embedding`后沿用了Moonshot时代的`_BATCH_SIZE=100`，DashScope硬性限制单次最多20条，chunk数一旦超过20整批请求直接400失败、全部跳过不报错也不重试单条。已改成20，详见`09_pipeline_run_status.md` #11-embed。

## 已知未解决问题

1. **东华大学招生计划**：网页端无可采集数据源，需决策改用第三方权威汇总源（如省考试院公布的招生计划本）还是人工从小程序截图录入
2. **复旦大学招生计划 2025/2026 年未公开发布**：按 PRD"官方未公开则明确标记缺失，不得推算或用旧数据顶替"处理，本轮不采集
3. **院校/学院/专业主数据（#10）**：学院/专业层实体表尚未设计建立，跟江苏#10现状一致，非本轮阻塞项
4. **复旦、交大：章程+专业介绍均无可采集正文来源**（反爬412/JS渲染SPA/无实质内容），详见上方"10校章程/专业介绍页——三个特殊情况"
5. **同济：专业介绍栏目无可采集正文来源**（经Playwright渲染确认，实际内容是专业名录一览表非介绍性文字），详见同上
6. **上海理工：专业介绍主要靠微信公众号外链承载**，采集可行性存疑，本轮未采集，详见同上
7. **🛑 并发浙江任务的RAG污染尚未清理，且规模已扩大**（2026-08-24复查）：`rag_documents`/`rag_chunks`是省份间共享表，浙江任务同一个`discovery_depth`默认值坑（见上方"关键技术方案沉淀"#7）在浙江工业大学/宁波大学/浙江师范大学/浙江大学/浙江理工大学/浙江工商大学等校的source上重复踩中，混入大量导航栏垃圾页（"联系我们""校园风光""首页""三位一体报名系统"，甚至标题就是翻页产物"3""6""8"）。上海自身8所章程数据抽查确认干净、未被污染，但**已实测观测到跨库检索精度被拉低**：查询"同济大学身体条件要求"时top-3命中了一条不相关的浙江工业大学章程片段。这不是本任务产生的，且数据在共享表里不隔离，按约定（"是谁开的谁清理"）等浙江任务自行处理，不代为清理，除非产品侧明确要求

## 快速恢复命令

```bash
# 采集单个数据源（本地venv，需要先 export DATABASE_URL="postgresql+asyncpg://wenjin:wenjin_dev@localhost:5432/wenjin"）
.venv/bin/python scripts/run_shanghai_pipeline.py --source <source_id> --raw-root data/raw --report-root data/reports --persist

# 发布（均已跑过，幂等重跑安全，会生成新的dataset_version）
.venv/bin/python scripts/publish_shanghai_admission_scores.py   # 内含采集+enrichment+发布
.venv/bin/python scripts/publish_shanghai_rank_segments.py
.venv/bin/python scripts/publish_shanghai_policy.py
.venv/bin/python scripts/publish_shanghai_admission_plans.py

# 业务表同步（复用现成脚本，province 无关，幂等）
.venv/bin/python scripts/sync_published_data_to_business_tables.py
```

容器内执行注意：backend容器`WORKDIR`是`/app`，要用`python -m scripts.xxx`（模块方式）；容器内默认没装pdfplumber最新版时先`pip install pdfplumber==0.11.7 openpyxl==3.1.5`（或`docker compose build`重建镜像使requirements.txt生效）。macOS Vision OCR（扫描版PDF/图片解析必需）只能在本地宿主机macOS环境跑，容器内是Linux会报"image OCR unavailable"。
