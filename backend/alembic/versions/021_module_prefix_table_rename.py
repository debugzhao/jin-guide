"""Rename all business tables with module-based prefixes for readability.

用户希望能通过表名快速识别所属业务模块（如 enrollment_data_admission_scores
一看就知道是"招生数据"模块，而不是裸的 admission_scores）。这次迁移只做纯粹的
ALTER TABLE/INDEX/CONSTRAINT RENAME，不改任何字段、不搬任何数据——所有 28 张
业务表按模块分组加前缀，agent_runs 本身已经是模块名，不加前缀。

命名分组：
  auth_            users, sessions
  candidate_       student_profiles, preferences
  agent_runs_      reports, volunteer_checks（agent_runs 表本身不改名）
  memory_          report_conversations, intake_conversations,
                   conversation_messages, conversation_summaries
  enrollment_data_ universities, admission_scores, admission_plans,
                   rank_segments, subject_requirements, rule_requirements,
                   province_thresholds
  pipeline_        data_sources, collection_runs, source_documents,
                   staging_records, dataset_versions, published_data_records
  rag_             documents, chunks
  notify_          notifications
  observability_   prompt_invocations

索引/约束名同步改名（避免下次 autogenerate 因为名字里还带着旧表名而产生噪音
diff）；LangGraph 的 checkpoints/checkpoint_blobs/checkpoint_writes/
checkpoint_migrations 表不是业务表，不在本次改动范围内。

Revision ID: 021_module_prefix_table_rename
Revises: 020_admission_plan_major_name
"""

from typing import Sequence, Union

from alembic import op

revision: str = "021_module_prefix_table_rename"
down_revision: Union[str, None] = "020_admission_plan_major_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (旧表名, 新表名)；agent_runs 保持不变，不出现在这个列表里
TABLE_RENAMES: list[tuple[str, str]] = [
    ("users", "auth_users"),
    ("sessions", "auth_sessions"),
    ("student_profiles", "candidate_student_profiles"),
    ("preferences", "candidate_preferences"),
    ("reports", "agent_runs_reports"),
    ("volunteer_checks", "agent_runs_volunteer_checks"),
    ("report_conversations", "memory_report_conversations"),
    ("intake_conversations", "memory_intake_conversations"),
    ("conversation_messages", "memory_conversation_messages"),
    ("conversation_summaries", "memory_conversation_summaries"),
    ("universities", "enrollment_data_universities"),
    ("admission_scores", "enrollment_data_admission_scores"),
    ("admission_plans", "enrollment_data_admission_plans"),
    ("rank_segments", "enrollment_data_rank_segments"),
    ("subject_requirements", "enrollment_data_subject_requirements"),
    ("rule_requirements", "enrollment_data_rule_requirements"),
    ("province_thresholds", "enrollment_data_province_thresholds"),
    ("data_sources", "pipeline_data_sources"),
    ("collection_runs", "pipeline_collection_runs"),
    ("source_documents", "pipeline_source_documents"),
    ("staging_records", "pipeline_staging_records"),
    ("dataset_versions", "pipeline_dataset_versions"),
    ("published_data_records", "pipeline_published_data_records"),
    ("documents", "rag_documents"),
    ("chunks", "rag_chunks"),
    ("notifications", "notify_notifications"),
    ("prompt_invocations", "observability_prompt_invocations"),
]

# 普通索引（非约束背书）：(旧索引名, 新索引名)。用 ALTER INDEX 改名，
# 与所属表当前叫什么无关，改名顺序不影响正确性。
INDEX_RENAMES: list[tuple[str, str]] = [
    ("ix_users_email", "ix_auth_users_email"),
    ("ix_sessions_user_id", "ix_auth_sessions_user_id"),
    ("ix_student_profiles_anonymous_id", "ix_candidate_student_profiles_anonymous_id"),
    ("ix_student_profiles_user_id", "ix_candidate_student_profiles_user_id"),
    ("ix_preferences_profile_id", "ix_candidate_preferences_profile_id"),
    ("ix_reports_anonymous_id", "ix_agent_runs_reports_anonymous_id"),
    ("ix_reports_created_at", "ix_agent_runs_reports_created_at"),
    ("ix_reports_parent_report_id", "ix_agent_runs_reports_parent_report_id"),
    ("ix_reports_profile_id", "ix_agent_runs_reports_profile_id"),
    ("ix_reports_run_id", "ix_agent_runs_reports_run_id"),
    ("ix_reports_user_id", "ix_agent_runs_reports_user_id"),
    ("ix_report_conversations_report_id", "ix_memory_report_conversations_report_id"),
    ("ix_report_conversations_user_id", "ix_memory_report_conversations_user_id"),
    ("ix_intake_conversations_owner_key", "ix_memory_intake_conversations_owner_key"),
    (
        "ix_intake_conversations_owner_key_updated_at",
        "ix_memory_intake_conversations_owner_key_updated_at",
    ),
    ("ix_conversation_messages_intake_seq", "ix_memory_conversation_messages_intake_seq"),
    ("ix_conversation_messages_report_seq", "ix_memory_conversation_messages_report_seq"),
    ("ix_universities_name", "ix_enrollment_data_universities_name"),
    ("ix_admission_scores_lookup", "ix_enrollment_data_admission_scores_lookup"),
    ("ix_admission_scores_university", "ix_enrollment_data_admission_scores_university"),
    ("ix_admission_plans_lookup", "ix_enrollment_data_admission_plans_lookup"),
    ("ix_rank_segments_lookup", "ix_enrollment_data_rank_segments_lookup"),
    ("ix_subject_req_university", "ix_enrollment_data_subject_req_university"),
    ("ix_subject_req_major", "ix_enrollment_data_subject_req_major"),
    ("ix_rule_requirements_target", "ix_enrollment_data_rule_requirements_target"),
    (
        "ix_province_thresholds_province_year",
        "ix_enrollment_data_province_thresholds_province_year",
    ),
    ("ix_data_sources_type_year", "ix_pipeline_data_sources_type_year"),
    ("ix_collection_runs_source_started", "ix_pipeline_collection_runs_source_started"),
    ("ix_source_documents_checksum", "ix_pipeline_source_documents_checksum"),
    ("ix_staging_records_review_status", "ix_pipeline_staging_records_review_status"),
    ("ix_staging_records_run", "ix_pipeline_staging_records_run"),
    ("ix_dataset_versions_lookup", "ix_pipeline_dataset_versions_lookup"),
    ("ix_published_records_lookup", "ix_pipeline_published_records_lookup"),
    ("ix_published_records_university", "ix_pipeline_published_records_university"),
    ("ix_documents_status", "ix_rag_documents_status"),
    ("ix_documents_year", "ix_rag_documents_year"),
    ("chunks_doc_province", "rag_chunks_doc_province"),
    ("chunks_embedding_hnsw", "rag_chunks_embedding_hnsw"),
    ("ix_chunks_document_id", "ix_rag_chunks_document_id"),
    ("ix_notifications_user_created", "ix_notify_notifications_user_created"),
    ("ix_prompt_invocations_created_at", "ix_observability_prompt_invocations_created_at"),
    ("ix_prompt_invocations_prompt_name", "ix_observability_prompt_invocations_prompt_name"),
    ("ix_prompt_invocations_status", "ix_observability_prompt_invocations_status"),
]

# 约束（主键/唯一/外键/check，含背后自动生成的同名索引）：
# (改名时约束所属表的当前名字, 旧约束名, 新约束名)。
# 用 ALTER TABLE ... RENAME CONSTRAINT，执行时机在对应表已经 RENAME TO 新名之后，
# 所以这里的表名一律用新名。
CONSTRAINT_RENAMES: list[tuple[str, str, str]] = [
    ("auth_users", "users_pkey", "auth_users_pkey"),
    ("auth_users", "users_openid_key", "auth_users_openid_key"),
    ("auth_users", "users_phone_key", "auth_users_phone_key"),
    ("auth_sessions", "sessions_pkey", "auth_sessions_pkey"),
    ("auth_sessions", "sessions_user_id_fkey", "auth_sessions_user_id_fkey"),
    ("candidate_student_profiles", "student_profiles_pkey", "candidate_student_profiles_pkey"),
    (
        "candidate_student_profiles",
        "student_profiles_user_id_fkey",
        "candidate_student_profiles_user_id_fkey",
    ),
    (
        "candidate_student_profiles",
        "student_profiles_source_message_id_fkey",
        "candidate_student_profiles_source_message_id_fkey",
    ),
    (
        "candidate_student_profiles",
        "fk_student_profiles_superseded_by",
        "fk_candidate_student_profiles_superseded_by",
    ),
    ("candidate_preferences", "preferences_pkey", "candidate_preferences_pkey"),
    (
        "candidate_preferences",
        "preferences_profile_id_fkey",
        "candidate_preferences_profile_id_fkey",
    ),
    (
        "candidate_preferences",
        "preferences_source_message_id_fkey",
        "candidate_preferences_source_message_id_fkey",
    ),
    (
        "candidate_preferences",
        "fk_preferences_superseded_by",
        "fk_candidate_preferences_superseded_by",
    ),
    ("agent_runs_reports", "reports_pkey", "agent_runs_reports_pkey"),
    ("agent_runs_reports", "reports_profile_id_fkey", "agent_runs_reports_profile_id_fkey"),
    ("agent_runs_reports", "reports_user_id_fkey", "agent_runs_reports_user_id_fkey"),
    ("agent_runs_reports", "reports_run_id_fkey", "agent_runs_reports_run_id_fkey"),
    (
        "agent_runs_reports",
        "reports_parent_report_id_fkey",
        "agent_runs_reports_parent_report_id_fkey",
    ),
    ("agent_runs_reports", "uq_reports_run_id", "uq_agent_runs_reports_run_id"),
    (
        "agent_runs_volunteer_checks",
        "volunteer_checks_pkey",
        "agent_runs_volunteer_checks_pkey",
    ),
    (
        "agent_runs_volunteer_checks",
        "volunteer_checks_profile_id_fkey",
        "agent_runs_volunteer_checks_profile_id_fkey",
    ),
    (
        "agent_runs_volunteer_checks",
        "volunteer_checks_report_id_fkey",
        "agent_runs_volunteer_checks_report_id_fkey",
    ),
    (
        "memory_report_conversations",
        "report_conversations_pkey",
        "memory_report_conversations_pkey",
    ),
    (
        "memory_report_conversations",
        "report_conversations_report_id_fkey",
        "memory_report_conversations_report_id_fkey",
    ),
    (
        "memory_report_conversations",
        "report_conversations_user_id_fkey",
        "memory_report_conversations_user_id_fkey",
    ),
    (
        "memory_intake_conversations",
        "intake_conversations_pkey",
        "memory_intake_conversations_pkey",
    ),
    (
        "memory_conversation_messages",
        "conversation_messages_pkey",
        "memory_conversation_messages_pkey",
    ),
    (
        "memory_conversation_messages",
        "conversation_messages_report_conversation_id_fkey",
        "memory_conversation_messages_report_conversation_id_fkey",
    ),
    (
        "memory_conversation_messages",
        "conversation_messages_intake_conversation_id_fkey",
        "memory_conversation_messages_intake_conversation_id_fkey",
    ),
    (
        "memory_conversation_messages",
        "uq_conversation_messages_report_seq",
        "uq_memory_conversation_messages_report_seq",
    ),
    (
        "memory_conversation_messages",
        "uq_conversation_messages_intake_seq",
        "uq_memory_conversation_messages_intake_seq",
    ),
    (
        "memory_conversation_messages",
        "ck_conversation_messages_exactly_one_parent",
        "ck_memory_conversation_messages_exactly_one_parent",
    ),
    (
        "memory_conversation_summaries",
        "conversation_summaries_pkey",
        "memory_conversation_summaries_pkey",
    ),
    (
        "memory_conversation_summaries",
        "conversation_summaries_report_conversation_id_fkey",
        "memory_conversation_summaries_report_conversation_id_fkey",
    ),
    (
        "memory_conversation_summaries",
        "conversation_summaries_intake_conversation_id_fkey",
        "memory_conversation_summaries_intake_conversation_id_fkey",
    ),
    (
        "memory_conversation_summaries",
        "uq_conversation_summaries_report",
        "uq_memory_conversation_summaries_report",
    ),
    (
        "memory_conversation_summaries",
        "uq_conversation_summaries_intake",
        "uq_memory_conversation_summaries_intake",
    ),
    (
        "memory_conversation_summaries",
        "ck_conversation_summaries_exactly_one_parent",
        "ck_memory_conversation_summaries_exactly_one_parent",
    ),
    ("enrollment_data_universities", "universities_pkey", "enrollment_data_universities_pkey"),
    (
        "enrollment_data_admission_scores",
        "admission_scores_pkey",
        "enrollment_data_admission_scores_pkey",
    ),
    (
        "enrollment_data_admission_scores",
        "admission_scores_university_id_fkey",
        "enrollment_data_admission_scores_university_id_fkey",
    ),
    (
        "enrollment_data_admission_plans",
        "admission_plans_pkey",
        "enrollment_data_admission_plans_pkey",
    ),
    (
        "enrollment_data_admission_plans",
        "admission_plans_university_id_fkey",
        "enrollment_data_admission_plans_university_id_fkey",
    ),
    ("enrollment_data_rank_segments", "rank_segments_pkey", "enrollment_data_rank_segments_pkey"),
    (
        "enrollment_data_subject_requirements",
        "subject_requirements_pkey",
        "enrollment_data_subject_requirements_pkey",
    ),
    (
        "enrollment_data_subject_requirements",
        "subject_requirements_university_id_fkey",
        "enrollment_data_subject_requirements_university_id_fkey",
    ),
    (
        "enrollment_data_rule_requirements",
        "rule_requirements_pkey",
        "enrollment_data_rule_requirements_pkey",
    ),
    (
        "enrollment_data_rule_requirements",
        "rule_requirements_source_id_fkey",
        "enrollment_data_rule_requirements_source_id_fkey",
    ),
    (
        "enrollment_data_province_thresholds",
        "province_thresholds_pkey",
        "enrollment_data_province_thresholds_pkey",
    ),
    ("pipeline_data_sources", "data_sources_pkey", "pipeline_data_sources_pkey"),
    ("pipeline_collection_runs", "collection_runs_pkey", "pipeline_collection_runs_pkey"),
    (
        "pipeline_collection_runs",
        "collection_runs_source_id_fkey",
        "pipeline_collection_runs_source_id_fkey",
    ),
    ("pipeline_source_documents", "source_documents_pkey", "pipeline_source_documents_pkey"),
    (
        "pipeline_source_documents",
        "source_documents_source_id_fkey",
        "pipeline_source_documents_source_id_fkey",
    ),
    (
        "pipeline_source_documents",
        "source_documents_collection_run_id_fkey",
        "pipeline_source_documents_collection_run_id_fkey",
    ),
    (
        "pipeline_source_documents",
        "uq_source_documents_source_checksum",
        "uq_pipeline_source_documents_source_checksum",
    ),
    ("pipeline_staging_records", "staging_records_pkey", "pipeline_staging_records_pkey"),
    (
        "pipeline_staging_records",
        "staging_records_source_document_id_fkey",
        "pipeline_staging_records_source_document_id_fkey",
    ),
    (
        "pipeline_staging_records",
        "staging_records_collection_run_id_fkey",
        "pipeline_staging_records_collection_run_id_fkey",
    ),
    (
        "pipeline_staging_records",
        "uq_staging_document_natural_key",
        "uq_pipeline_staging_document_natural_key",
    ),
    ("pipeline_dataset_versions", "dataset_versions_pkey", "pipeline_dataset_versions_pkey"),
    (
        "pipeline_dataset_versions",
        "dataset_versions_name_key",
        "pipeline_dataset_versions_name_key",
    ),
    (
        "pipeline_dataset_versions",
        "uq_dataset_version_scope",
        "uq_pipeline_dataset_version_scope",
    ),
    (
        "pipeline_published_data_records",
        "published_data_records_pkey",
        "pipeline_published_data_records_pkey",
    ),
    (
        "pipeline_published_data_records",
        "published_data_records_dataset_version_id_fkey",
        "pipeline_published_data_records_dataset_version_id_fkey",
    ),
    (
        "pipeline_published_data_records",
        "uq_published_dataset_natural_key",
        "uq_pipeline_published_dataset_natural_key",
    ),
    ("rag_documents", "documents_pkey", "rag_documents_pkey"),
    (
        "rag_documents",
        "documents_source_document_id_fkey",
        "rag_documents_source_document_id_fkey",
    ),
    (
        "rag_documents",
        "uq_documents_source_document_id",
        "uq_rag_documents_source_document_id",
    ),
    ("rag_chunks", "chunks_pkey", "rag_chunks_pkey"),
    ("rag_chunks", "chunks_document_id_fkey", "rag_chunks_document_id_fkey"),
    ("notify_notifications", "notifications_pkey", "notify_notifications_pkey"),
    (
        "notify_notifications",
        "notifications_user_id_fkey",
        "notify_notifications_user_id_fkey",
    ),
    (
        "observability_prompt_invocations",
        "prompt_invocations_pkey",
        "observability_prompt_invocations_pkey",
    ),
]


def upgrade() -> None:
    for old, new in TABLE_RENAMES:
        op.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
    for old, new in INDEX_RENAMES:
        op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')
    for table, old, new in CONSTRAINT_RENAMES:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')


def downgrade() -> None:
    for table, old, new in CONSTRAINT_RENAMES:
        # downgrade 时表已经是新名，RENAME CONSTRAINT 用当前（新）表名执行
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{new}" TO "{old}"')
    for old, new in INDEX_RENAMES:
        op.execute(f'ALTER INDEX "{new}" RENAME TO "{old}"')
    for old, new in TABLE_RENAMES:
        op.execute(f'ALTER TABLE "{new}" RENAME TO "{old}"')
