# 浙江 Top10 数据采集 — 任务执行状态看板

> 更新时间：2026-08-22 | 参考：`09_pipeline_run_status.md`（江苏看板同构）
> 用途：随时查看每个子任务当前卡在哪一步，快速定位下一步命令，不用重新翻代码
> 白名单口径：艾瑞深校友会网《2025校友会中国大学排名》浙江省内前10（用户已确认，见下方§1），非动态排名结果

## 状态图例

✅ 完成 ｜ ⚠️ 部分完成（有产出但卡在某一步） ｜ ❌ 未开始 ｜ 🛑 阻塞在外部依赖（需人决策/协调） ｜ 🔧 代码适配中（不是数据任务，是"能否复用"的前提）

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
| 3 | 2026 招生计划（10校，`admission_plan`） | ⚠️ | 5校已登记有信心的URL，尚未实际跑Implement验证（还未确认这5个页面能被现有`parse_admission_plan_rows`正确解析，很可能同样需要按各校真实表头调整，参考#1的经验）。**5校未登记**：浙大/西湖大学官网无承载页；杭电/浙师大栏目静态但未定位到2025/2026年具体条目；温州医科大学数据在微信公众号文章里 |
| 4 | 2025/2026 招生政策（`policy`） | ✅ | **已用真实数据跑通并验证**：`--source zjzs-policy-2026`真实拉取通知页+docx附件（zjzs.net的附件是`downfile.jsp?...&filename=x.docx`下载代理端点，不是直链，过程中发现并修复了3个连带bug，见下方"Implement阶段发现的新问题"），docx正文提取出11条`DocumentChunkRecord`（内容可读、非乱码）+ 1条`valid`的`PolicyRuleRecord`（`volunteer_mode=parallel`, `max_volunteers=80`，已用真实政策原文验证准确）+ 1条`needs_review`（来自入口公告页本身，同江苏#4"空壳公告页"模式） |
| 5-8 | 2023/2024 分数线+分数段表 | ❌ | 未Discover，浙江"3+3"是2014年后逐步推行，需先确认2023/2024年官方是否仍用同名"分数段表"格式，不能假设跟2025/2026一致 |
| 9 | 10校专业录取线 | ❌ | 未登记数据源 |
| 10 | 院校/学院/专业主数据 | ❌ | 未登记数据源，且浙江"专业(类)+学校"模式下专业主数据的粒度需要重新设计 |
| 11 | 10校章程/专业介绍/转专业政策（RAG） | 🛑 | 依赖：同江苏#11，仍受Moonshot账户embedding权限阻塞（见`09_pipeline_run_status.md`#11，全局性阻塞非浙江专属） |
| 12 | 教育部院校/专业标准目录 | ❌ | 未登记数据源（可与江苏共用同一份目录，不需要按省份重复采集） |
| 13 | 业务表同步 loader | ❌ | 依赖#1/#2/#4先产出可发布数据 |

### Implement 阶段已发现并修复的问题（用真实线上数据验证过，非假设）

- **policy 附件是 docx 不是 pdf**：新增 `extract_document_text` 的 `.docx` 解析分支（`python-docx`，已加入`requirements.txt`），按文档原始顺序读段落+表格。已用真实2026年浙江政策docx验证提取效果正常（非乱码）。
- **zjzs.net 附件是下载代理端点，不是直链**：附件真实URL是`/module/download/downfile.jsp?...&filename=x.docx`，扩展名藏在query参数里，不在URL路径里。修了两处：`discovery.py::discover_links`（原来只查`parsed.path`的后缀，现在也查query参数值）和`raw_store.py::_safe_suffix`（同理，且发现这个下载端点的`Content-Type`响应头被服务器错误标成`text/html`——**如果不查query参数会把docx文件误存成`.html`再被当成HTML乱码解析**，已用真实响应头验证过这个坏case确实会发生）。
- **`extract_policy_rule`的`max_volunteers`正则**：浙江政策原文实际用词是"专业平行志愿"+"考生每次可填报不超过80个志愿"（不是笔者最初猜测的"专业(类)+学校"），且同一份文档里还有"传统志愿"轨道下不相关的"5个院校志愿""6个专业志愿"两个干扰数字，第一版正则曾误抓到"1个志愿"（来自"1个志愿单位"这句说明性文字）。最终用`不超过(\d{1,3})个志愿(?!单位|专业|院校)`精确锁定，已用真实文档验证提取出正确的`80`，并补了两条回归测试（`test_parsing_and_validation.py`，江苏用例+浙江用例各一条）覆盖这个坑。
- **`run_jiangsu_pipeline.py`硬编码只认`jiangsu.yaml`**：脚本本身跟省份无关，加了`--config`参数（默认仍指向jiangsu.yaml不破坏现有文档里记录的命令），本次浙江所有真实数据验证都是用这个脚本跑的。
- **admission_score新写`parse_zhejiang_admission_score_rows`**（`data_pipeline/parsers/tabular.py`）：浙江扁平表结构（学校代号/学校名称/专业代号/专业名称/计划数/分数线/位次）跟江苏合并单元格格式完全不同，新写专用函数而不是改`parse_admission_score_rows`的别名（避免把江苏那份搞复杂）；`jobs/collect.py`按`config.province`分派到对应解析函数，并新增`_infer_zhejiang_stage`从标题识别"第一段/第二段"写入`batch`字段。已用真实2026年第一段xls验证：401条全部valid。

### 已知会卡住的坑（新发现，用真实数据验证过）

- **西湖大学不在标准投档线表里**：9/10白名单校在admission_score真实数据里有记录，西湖大学0条——已核实不是解析bug，是它招生规模极小、走"创新班"等特殊渠道，数据只存在于招生简章正文，不在这类结构化文件里。发布/展示时不能对西湖大学的admission_score留白，要明确标"不适用"而不是"未采集"。

## §5 推荐执行顺序

```
①#0a-0d 代码适配（阻塞一切浙江数据正确落库，工作量S）                         ✅ 已完成 2026-08-22
②省级source Discover+登记（policy/rank_segment/admission_score共8条 + 5校admission_plan） ✅ 已完成 2026-08-22
③#4 policy 端到端跑通验证（docx解析+zjzs.net下载代理端点+policy正则三个连带bug）     ✅ 已完成 2026-08-22
④#2 rank_segment 端到端跑通验证（428条valid，0 needs_review/rejected）           ✅ 已完成 2026-08-22
⑤#1 admission_score 端到端跑通验证（新写浙江专用解析函数，401条valid）             ✅ 已完成 2026-08-22
⑥#3 10校招生计划：5校已登记的先跑通；浙大/西湖/杭电/浙师大/温医5校缺口需人工决策    ← 下一步
⑦#9/#10/#12 与江苏同等次序靠后
⑧#11 RAG，卡点在Moonshot权限，与江苏共享同一个阻塞
```

## 已知会卡住的坑

- ~~浙江`major_group_code`字段怎么填~~ 已解决：`parse_zhejiang_admission_score_rows`复用`major_group_code`/`major_group_name`存专业代号/专业名称，理由是浙江"1个专业(类)"和江苏"1个院校专业组"同为最小志愿单位，语义对得上
- 西湖大学的 `ownership` 无法用现有 `central`/`provincial` 二值描述，已在yaml里留空，后续如果要在其他代码里按ownership分组统计需要注意这条记录会被漏统计
- RAG embedding 阻塞是全局性的（Moonshot账户权限），不是浙江任务新引入的问题，见`09_pipeline_run_status.md`#11
