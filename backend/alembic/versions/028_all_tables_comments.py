"""Add table/column comments to all remaining business tables.

给剩余尚未加注释的业务表（鉴权、考生档案、Agent 运行、招生数据、RAG、通知、
Prompt 观测、数据采集管线共 23 张表）补齐 DB 级注释；顺带把 005 迁移里遗留的
两条英文字段注释（agent_runs.debug_summary_json / duration_seconds）统一改
成中文风格。LangGraph 自动建表的 checkpoints/checkpoint_blobs/checkpoint_writes/
checkpoint_migrations 不受 Alembic 管理，新库首次 `alembic upgrade head` 时这些
表还不存在，直接 COMMENT ON 会报错，所以用 DO 块加 to_regclass 存在性检查包裹，
表不存在时静默跳过；alembic_version 是 Alembic 自身的记录表，任何迁移执行前必然
已存在，可以直接注释。只加注释，不改字段/约束/索引，属于纯文档性变更。

Revision ID: 028_all_tables_comments
Revises: 027_conversation_comments
"""

from typing import Sequence, Union

from alembic import op

revision: str = "028_all_tables_comments"
down_revision: Union[str, None] = "027_conversation_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_COMMENTS = {
    "auth_users": "用户账号表：邮箱+密码鉴权，预留微信OAuth(openid)",
    "auth_sessions": "登录会话表：session token对应的会话记录",
    "candidate_student_profiles": (
        "考生档案表：分数/位次/选科/预算/风格等建档信息，Preference/Report/"
        "AgentRun等均挂靠于此"
    ),
    "candidate_preferences": (
        "考生偏好表：意向专业/城市/排斥项/职业优先级，与考生档案一对多"
    ),
    "agent_runs": (
        "Agent运行记录表：跟踪一次LangGraph任务的状态/成本/耗时，"
        "通过thread_id关联LangGraph checkpoint"
    ),
    "agent_runs_reports": "志愿方案报告表：冲稳保方案、风险评分、证据链等报告结果",
    "agent_runs_volunteer_checks": "志愿表体检记录表：对已填报志愿表做风险检测的结果",
    "enrollment_data_admission_scores": (
        "历年录取分数线表，按年份/省份/批次/科类维度记录院校投档线"
    ),
    "enrollment_data_rank_segments": (
        "省份位次段表，记录某年某省某科类下分数到全省累计位次的映射"
    ),
    "enrollment_data_subject_requirements": (
        "选科要求表：院校专业对高考选科及体检指标的限制"
    ),
    "enrollment_data_admission_plans": (
        "招生计划表：某年份/省份/批次下具体专业(组)的招生名额/学费等计划信息，"
        "区别于admission_scores历年投档线"
    ),
    "enrollment_data_rule_requirements": (
        "规则配置表：选科/体检/批次等规则的可追溯配置及来源引用"
    ),
    "enrollment_data_province_thresholds": (
        "省份级冲稳保位次阈值与志愿数上限配置表"
    ),
    "rag_documents": "RAG文档表：切块前的原始/已处理文档及其状态、权威等级",
    "rag_chunks": "RAG切块表：文档切块内容及向量表示，供检索使用",
    "notify_notifications": "站内通知表",
    "observability_prompt_invocations": (
        "Prompt调用观测表：记录Prompt版本、模型、耗时、状态，不保存用户原文"
    ),
    "pipeline_data_sources": "数据采集源配置表：定义采集入口、解析器、更新频率等",
    "pipeline_collection_runs": "数据采集运行记录表：一次采集任务的执行状态与统计",
    "pipeline_source_documents": "采集原始文档表：采集到的原始文件及去重校验和",
    "pipeline_staging_records": "数据加工暂存表：解析后待复核的结构化记录",
    "pipeline_dataset_versions": "数据集版本表：数据发布的版本管理",
    "pipeline_published_data_records": "已发布数据记录表：正式对外提供服务的数据快照",
}

_COLUMN_COMMENTS = {
    "auth_users": {
        "id": "用户主键UUID",
        "email": "登录邮箱，唯一，允许为空(预留非邮箱登录方式)",
        "password_hash": "密码哈希，允许为空(预留非密码登录方式)",
        "email_verified": "邮箱是否已通过验证码校验",
        "openid": "微信OAuth openid，二期预留字段",
        "role": "用户角色：user/admin",
        "created_at": "用户创建时间",
    },
    "auth_sessions": {
        "id": "会话主键UUID",
        "user_id": "登录用户id，匿名会话为空",
        "anonymous_id": "匿名会话标识，登录用户为空",
        "expires_at": "会话过期时间",
        "created_at": "会话创建时间",
    },
    "candidate_student_profiles": {
        "id": "档案主键UUID",
        "user_id": "登录用户id，匿名建档阶段为空",
        "anonymous_id": "匿名建档阶段草稿归属标识，登录/注册后绑定到user_id",
        "province": "考生所在省份",
        "score": "高考总分",
        "rank": "全省位次",
        "subjects": "选科列表(JSON数组)，如[\"物理\",\"化学\"]",
        "batch": "报考批次，默认本科批",
        "family_budget": "年度学费预算，单位：元",
        "risk_style": "冲稳保风格：conservative/balanced/aggressive",
        "completeness_score": "档案完整度评分",
        "created_at": "创建时间",
        "updated_at": "最后更新时间",
        "source_type": (
            "数据来源：user_explicit(用户表单/聊天明确填写)/model_inferred"
            "(AI从对话推断，当前未接入提取逻辑)"
        ),
        "confidence": "推断置信度，仅source_type=model_inferred时有意义",
        "status": "记录状态：confirmed/proposed/rejected/superseded",
        "last_confirmed_at": "最近一次确认时间",
        "source_message_id": "来源对话消息id，表单提交场景恒为空",
        "superseded_by": "被哪条新记录取代(自引用)，保留历史变更链条",
        "superseded_at": "被取代时间",
    },
    "candidate_preferences": {
        "id": "偏好记录主键UUID",
        "profile_id": "关联的考生档案id",
        "major_prefs": "意向专业列表(JSON数组)",
        "city_prefs": "意向城市列表(JSON数组)",
        "rejected_majors": "排斥专业列表(JSON数组)",
        "career_priority": "职业发展优先级",
        "created_at": "创建时间",
        "updated_at": "最后更新时间",
        "source_type": (
            "数据来源：user_explicit(用户表单/聊天明确填写)/model_inferred"
            "(AI从对话推断，当前未接入提取逻辑)"
        ),
        "confidence": "推断置信度，仅source_type=model_inferred时有意义",
        "status": "记录状态：confirmed/proposed/rejected/superseded",
        "last_confirmed_at": "最近一次确认时间",
        "source_message_id": "来源对话消息id，表单提交场景恒为空",
        "superseded_by": "被哪条新记录取代(自引用)，保留历史变更链条",
        "superseded_at": "被取代时间",
    },
    "agent_runs": {
        "id": "运行记录主键UUID",
        "thread_id": "LangGraph checkpoint系统使用的唯一thread id",
        "user_id": "登录用户id，匿名会话为空",
        "anonymous_id": "匿名会话发起标识，用于把产出的Report正确归属",
        "profile_id": "关联的考生档案id",
        "task_type": "任务类型：generate_report/check_volunteer",
        "status": "运行状态：queued/running/interrupted/completed/failed/timeout",
        "cost_tokens": "累计消耗token数",
        "cost_usd": "累计消耗成本，单位：美元",
        "trace_url": "可观测性平台(如LangSmith)的trace链接",
        "error_msg": "失败时记录的错误信息",
        "debug_summary_json": (
            "汇总的调试遥测数据：node_timings/tool_call_summary/state_summary/"
            "cost_breakdown，供Admin Debug Console展示"
        ),
        "duration_seconds": "实际运行耗时，单位：秒，完成时写入",
        "created_at": "创建时间",
        "completed_at": "运行完成时间",
    },
    "agent_runs_reports": {
        "id": "报告主键UUID",
        "profile_id": "关联的考生档案id",
        "user_id": "登录用户id",
        "anonymous_id": "匿名建档阶段生成的报告归属，登录/注册后绑定到user_id",
        "run_id": (
            "关联的agent_runs id，唯一：reflection重试循环内多次report节点执行"
            "按run_id upsert同一行，不重复插入"
        ),
        "status": "报告状态：generating/completed/failed",
        "risk_level": "风险等级：low/medium/high",
        "risk_score": "风险评分",
        "plan_json": "冲稳保三档结构化方案(conservative/balanced/aggressive)",
        "evidence_json": "直接内嵌的证据链",
        "dataset_version": "生成时使用的数据集版本",
        "version": "同一血缘链内版本号，从1递增",
        "parent_report_id": "/refine产出新版本时指向被refine的原报告",
        "run_summary_json": "用户可见的生成过程摘要，供报告页决策过程回放卡片使用",
        "created_at": "创建时间",
        "deleted_at": "软删除时间",
    },
    "agent_runs_volunteer_checks": {
        "id": "体检记录主键UUID",
        "profile_id": "关联的考生档案id",
        "report_id": "关联的报告id",
        "risk_items_json": "风险条目对象列表",
        "overall_risk_level": "整体风险等级：low/medium/high",
        "status": "状态：pending/completed",
        "created_at": "创建时间",
    },
    "enrollment_data_admission_scores": {
        "id": "记录主键UUID",
        "university_id": "关联院校id",
        "year": "年份",
        "province": "招生省份",
        "batch": "批次：本科批/专科批/提前批",
        "subject_type": "科类：physics/history",
        "major_category": "专业大类，为空表示全校口径",
        "min_score": "最低录取分",
        "min_rank": "最低录取位次",
        "avg_score": "平均录取分",
        "avg_rank": "平均录取位次",
        "max_score": "最高录取分",
        "enrollment_count": "实际录取人数",
    },
    "enrollment_data_rank_segments": {
        "id": "记录主键UUID",
        "year": "年份",
        "province": "省份",
        "subject_type": "科类：physics/history",
        "score": "分数",
        "cumulative_rank": "该分数对应的全省累计位次",
    },
    "enrollment_data_subject_requirements": {
        "id": "记录主键UUID",
        "university_id": "关联院校id",
        "major_name": "专业名称",
        "required_subjects": "必选科目列表(JSON)，如[\"物理\"]，空数组表示不限",
        "optional_subjects": "可选科目候选列表(JSON)，需从中至少选N门",
        "optional_required_count": "需从optional_subjects中至少选修的门数",
        "restricted_subjects": "限选科目列表(JSON)：选了则不可报考该专业，极少见",
        "medical_restrictions": (
            "体检受限说明(JSON)，如{\"color_blind\": \"不招\", \"height_min\": 155}"
        ),
    },
    "enrollment_data_admission_plans": {
        "id": "记录主键UUID",
        "year": "年份",
        "province": "招生省份",
        "batch": "批次",
        "university_id": "关联院校id",
        "major_group": "专业组",
        "major_code": "专业代码，仅省考试院正式招生计划文件带该字段",
        "major_name": "专业名称",
        "subject_type": "科类：physics/history/unified，用于配合major_name区分同校同批次下不同专业",
        "admission_type": (
            "招生类型(如普通类/三位一体等)，用于区分不分文理省份下同名专业的"
            "不同录取机制"
        ),
        "restrictions": (
            "备注限制条件，用于拆分同校同批次同专业名称下按备注互斥的多条招生线"
        ),
        "quota": "招生计划数",
        "subjects": "选科要求(JSON)",
        "tuition": "学费，单位：元/年",
        "dataset_version": "数据集版本",
        "created_at": "创建时间",
    },
    "enrollment_data_rule_requirements": {
        "id": "记录主键UUID",
        "type": "规则类型",
        "province": "适用省份，可为空表示通用",
        "year": "适用年份，可为空表示通用",
        "target_id": "规则作用的目标对象id",
        "rule_json": "规则内容(JSON)",
        "source_id": "关联的rag_documents来源文档id，用于追溯规则出处",
        "created_at": "创建时间",
    },
    "enrollment_data_province_thresholds": {
        "id": "记录主键UUID",
        "province": "省份",
        "year": "年份",
        "high_rush_rank_gap": "冲得较高档位次差阈值",
        "rush_rank_gap_min": "冲档位次差下限",
        "rush_rank_gap_max": "冲档位次差上限",
        "target_rank_gap": "稳档位次差阈值",
        "safe_rank_gap": "保档位次差阈值",
        "max_volunteers": "该省该年志愿数上限",
    },
    "rag_documents": {
        "id": "文档主键UUID",
        "type": (
            "文档类型：admission_plan/admission_score/rank_segment/charter/"
            "major_intro/employment_report/policy"
        ),
        "title": "文档标题",
        "source_url": "文档来源URL",
        "year": "文档对应年份",
        "authority_level": "权威等级：official/semi-official/third-party/internal",
        "checksum": "文件内容SHA256校验和，用于去重",
        "source_document_id": "关联的采集原始文档id",
        "raw_storage_path": "原始文件存储路径",
        "status": "文档状态：raw/parsed/verified/published/deprecated",
        "created_at": "创建时间",
        "deleted_at": "软删除时间",
    },
    "rag_chunks": {
        "id": "切块主键UUID",
        "document_id": "关联的rag_documents id",
        "content": "切块正文",
        "embedding": "向量表示，1024维",
        "embedding_model": "生成该embedding所用的模型标识，用于迁移时按模型过滤",
        "metadata_json": "元数据(JSON)：省份、年份、university_id、major_id、page_num等",
        "created_at": "创建时间",
    },
    "notify_notifications": {
        "id": "通知主键UUID",
        "user_id": "接收通知的用户id",
        "type": "通知类型",
        "payload_json": "通知内容负载(JSON)",
        "read_at": "已读时间，为空表示未读",
        "created_at": "创建时间",
    },
    "observability_prompt_invocations": {
        "id": "调用记录主键UUID",
        "prompt_name": "Prompt名称",
        "prompt_version": "Prompt版本号",
        "prompt_hash": "Prompt内容哈希，用于校验版本一致性",
        "model_alias": "调用的LiteLLM虚拟模型别名",
        "status": "调用状态",
        "latency_ms": "调用耗时，单位：毫秒",
        "error_type": "失败时的错误类型",
        "context_json": "调用上下文(JSON)，不含用户原文和动态上下文",
        "created_at": "创建时间",
    },
    "pipeline_data_sources": {
        "id": "数据源主键标识",
        "name": "数据源名称",
        "entry_url": "采集入口URL",
        "data_type": "数据类型",
        "year": "对应年份，可为空",
        "target_university_code": "定向采集的目标院校代码，可为空",
        "collection_method": "采集方式",
        "parser": "使用的解析器标识",
        "update_frequency": "更新频率",
        "authority_level": "权威等级",
        "enabled": "是否启用该数据源",
        "last_success_at": "最近一次成功采集时间",
        "last_checksum": "最近一次采集内容的校验和",
        "created_at": "创建时间",
        "updated_at": "最后更新时间",
    },
    "pipeline_collection_runs": {
        "id": "采集运行主键UUID",
        "source_id": "关联的数据源id",
        "status": "运行状态，默认running",
        "started_at": "开始时间",
        "finished_at": "结束时间",
        "artifact_count": "采集到的原始文件数",
        "parsed_count": "解析成功数",
        "valid_count": "校验通过数",
        "review_count": "待人工复核数",
        "rejected_count": "校验拒绝数",
        "error_message": "失败时的错误信息",
    },
    "pipeline_source_documents": {
        "id": "原始文档主键UUID",
        "source_id": "关联的数据源id",
        "collection_run_id": "所属采集运行id",
        "source_url": "文档来源URL",
        "title": "文档标题",
        "checksum": "内容SHA256校验和，用于同源去重",
        "storage_path": "原始文件存储路径",
        "content_type": "文件内容类型",
        "size_bytes": "文件大小，单位：字节",
        "status": "状态，默认raw",
        "collected_at": "采集时间",
    },
    "pipeline_staging_records": {
        "id": "暂存记录主键UUID",
        "source_document_id": "关联的原始文档id",
        "collection_run_id": "所属采集运行id",
        "record_type": "记录类型",
        "natural_key": "业务自然键，用于同文档内去重",
        "review_status": "复核状态",
        "payload_json": "解析后的结构化内容(JSON)",
        "issues_json": "校验发现的问题列表(JSON)",
        "reviewed_by": "复核人",
        "reviewed_at": "复核时间",
        "created_at": "创建时间",
    },
    "pipeline_dataset_versions": {
        "id": "数据集版本主键UUID",
        "name": "数据集版本名称，唯一",
        "dataset_type": "数据集类型",
        "province": "省份",
        "year": "年份",
        "version": "版本号",
        "status": "状态，默认draft",
        "record_count": "记录数",
        "manifest_json": "版本清单(JSON)",
        "created_at": "创建时间",
        "published_at": "发布时间",
    },
    "pipeline_published_data_records": {
        "id": "已发布记录主键UUID",
        "dataset_version_id": "关联的数据集版本id",
        "record_type": "记录类型",
        "natural_key": "业务自然键，用于同版本内去重",
        "province": "省份",
        "year": "年份",
        "subject_type": "科类，可为空",
        "batch": "批次，可为空",
        "university_code": "院校代码，可为空",
        "major_group_code": "专业组代码，可为空",
        "major_code": "专业代码，可为空",
        "payload_json": "发布内容(JSON)",
        "provenance_json": "数据血缘/来源信息(JSON)",
        "created_at": "创建时间",
    },
}

# alembic自身的迁移记录表：先于任何migration执行前必然已存在，可直接注释
_ALEMBIC_TABLE_COMMENT = "Alembic自身的迁移版本记录表：记录数据库当前已应用到的最新migration revision"
_ALEMBIC_COLUMN_COMMENTS = {
    "version_num": "当前已应用的迁移revision id",
}

# LangGraph checkpointer 自动建表，不受Alembic管理；新库首次跑迁移时这些表还不
# 存在，用 to_regclass 存在性检查包裹，表不存在时静默跳过，已存在的环境(本地/
# 已初始化过的生产库)立即生效
_CHECKPOINT_TABLE_COMMENTS = {
    "checkpoints": "LangGraph自动管理的检查点表：记录每次graph执行的state快照，非业务表，不在Alembic迁移中新建",
    "checkpoint_blobs": "LangGraph自动管理的检查点大字段存储表：按channel/version存储序列化后的state值",
    "checkpoint_writes": "LangGraph自动管理的检查点待写入表：记录每个task对各channel的写入，用于恢复执行",
    "checkpoint_migrations": "LangGraph内部的schema版本记录表：记录checkpoint相关表结构已应用到的迁移版本号",
}
_CHECKPOINT_COLUMN_COMMENTS = {
    "checkpoints": {
        "thread_id": "会话/运行线程id，对应agent_runs.thread_id",
        "checkpoint_ns": "检查点命名空间，子图场景下区分层级，默认空字符串",
        "checkpoint_id": "检查点唯一id",
        "parent_checkpoint_id": "父检查点id，用于回溯执行链路",
        "type": "state序列化类型",
        "checkpoint": "序列化的state快照(jsonb)",
        "metadata": "检查点元数据(jsonb)，如写入来源节点",
    },
    "checkpoint_blobs": {
        "thread_id": "会话/运行线程id",
        "checkpoint_ns": "检查点命名空间，默认空字符串",
        "channel": "state中的字段(channel)名",
        "version": "该channel的版本号",
        "type": "序列化类型",
        "blob": "序列化后的二进制内容",
    },
    "checkpoint_writes": {
        "thread_id": "会话/运行线程id",
        "checkpoint_ns": "检查点命名空间，默认空字符串",
        "checkpoint_id": "所属检查点id",
        "task_id": "写入所属的task id",
        "idx": "同一task内写入的序号",
        "channel": "写入的state字段(channel)名",
        "type": "序列化类型",
        "blob": "序列化后的二进制内容",
        "task_path": "task在图中的路径",
    },
    "checkpoint_migrations": {
        "v": "已应用的迁移版本号",
    },
}


def _quote(text: str) -> str:
    return text.replace("'", "''")


def upgrade() -> None:
    for table, comment in _TABLE_COMMENTS.items():
        op.execute(f"COMMENT ON TABLE {table} IS '{_quote(comment)}'")
    for table, columns in _COLUMN_COMMENTS.items():
        for column, comment in columns.items():
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS '{_quote(comment)}'")

    op.execute(f"COMMENT ON TABLE alembic_version IS '{_quote(_ALEMBIC_TABLE_COMMENT)}'")
    for column, comment in _ALEMBIC_COLUMN_COMMENTS.items():
        op.execute(f"COMMENT ON COLUMN alembic_version.{column} IS '{_quote(comment)}'")

    for table, comment in _CHECKPOINT_TABLE_COMMENTS.items():
        stmts = [f"COMMENT ON TABLE {table} IS '{_quote(comment)}';"]
        for column, col_comment in _CHECKPOINT_COLUMN_COMMENTS[table].items():
            stmts.append(f"COMMENT ON COLUMN {table}.{column} IS '{_quote(col_comment)}';")
        body = "\n    ".join(stmts)
        op.execute(
            f"""
            DO $$
            BEGIN
              IF to_regclass('public.{table}') IS NOT NULL THEN
                {body}
              END IF;
            END $$;
            """
        )


def downgrade() -> None:
    for table in _CHECKPOINT_TABLE_COMMENTS:
        stmts = [f"COMMENT ON TABLE {table} IS NULL;"]
        for column in _CHECKPOINT_COLUMN_COMMENTS[table]:
            stmts.append(f"COMMENT ON COLUMN {table}.{column} IS NULL;")
        body = "\n    ".join(stmts)
        op.execute(
            f"""
            DO $$
            BEGIN
              IF to_regclass('public.{table}') IS NOT NULL THEN
                {body}
              END IF;
            END $$;
            """
        )

    op.execute("COMMENT ON TABLE alembic_version IS NULL")
    for column in _ALEMBIC_COLUMN_COMMENTS:
        op.execute(f"COMMENT ON COLUMN alembic_version.{column} IS NULL")

    for table in _TABLE_COMMENTS:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
    for table, columns in _COLUMN_COMMENTS.items():
        for column in columns:
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS NULL")
