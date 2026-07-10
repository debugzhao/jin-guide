MOCK_REPORT_PLAN = {
    "profile_summary": {
        "province": "河南",
        "score": 612,
        "rank": 32680,
        "subjects": ["物理", "化学"]
    },
    "condition_commentary": "你的地域偏好（仅限郑州）和预算（≤6000元/年）同时设置较紧，符合条件的候选数量有限；如果放宽地域偏好，候选会更充分。",
    "risk_level": "high",
    "risk_items": [
        {"level": "warning", "description": "填报的临床医学专业涉及医学体检色觉限制，请核实考生体检档案。"},
        {"level": "info", "description": "保底学校数量充足，方案整体安全系数较高。"}
    ],
    "plans": [
        {
            "type": "balanced",
            "candidates": [
                {
                    "id": "cand-001",
                    "university_id": "univ-001",
                    "university_name": "郑州大学",
                    "university_city": "郑州",
                    "tier": "target",
                    "major_name": "软件工程",
                    "major_group": "专业组01",
                    "admission_safety_score": 75.0,
                    "matching_confidence_score": 78.0,
                    "overall_score": 85.0,
                    "tuition_per_year": 5500,
                    "subject_requirements": ["物理", "化学"],
                    "historical_ranks": [{"year": 2025, "min_rank": 35200}, {"year": 2024, "min_rank": 34100}],
                    "recommendation_reasons": ["考生位次高出郑州大学软件工程近3年平均位次3000名", "考生倾向郑州市高校，离家近"],
                    "evidence_ids": ["ev-001"]
                },
                {
                    "id": "cand-002",
                    "university_id": "univ-002",
                    "university_name": "河南大学",
                    "university_city": "开封",
                    "tier": "safe",
                    "major_name": "计算机科学与技术",
                    "major_group": "专业组02",
                    "admission_safety_score": 88.0,
                    "matching_confidence_score": 82.0,
                    "overall_score": 78.0,
                    "tuition_per_year": 5000,
                    "subject_requirements": ["物理"],
                    "historical_ranks": [{"year": 2025, "min_rank": 45300}, {"year": 2024, "min_rank": 44800}],
                    "recommendation_reasons": ["分数处于安全区间，可作为绝佳的稳妥保底院校"],
                    "evidence_ids": ["ev-002"]
                }
            ]
        },
        {
            "type": "conservative",
            "candidates": [
                {
                    "id": "cand-002",
                    "university_id": "univ-002",
                    "university_name": "河南大学",
                    "university_city": "开封",
                    "tier": "safe",
                    "major_name": "计算机科学与技术",
                    "major_group": "专业组02",
                    "admission_safety_score": 88.0,
                    "overall_score": 78.0,
                    "tuition_per_year": 5000,
                    "subject_requirements": ["物理"],
                    "recommendation_reasons": ["保守型推荐，作为强力保底支撑"],
                    "evidence_ids": ["ev-002"]
                }
            ]
        },
        {
            "type": "aggressive",
            "candidates": [
                {
                    "id": "cand-003",
                    "university_id": "univ-003",
                    "university_name": "西安交通大学",
                    "university_city": "西安",
                    "tier": "rush",
                    "major_name": "电子信息科学与技术",
                    "major_group": "专业组01",
                    "admission_safety_score": 45.0,
                    "matching_confidence_score": 58.0,
                    "overall_score": 92.0,
                    "tuition_per_year": 6000,
                    "subject_requirements": ["物理", "化学"],
                    "historical_ranks": [{"year": 2025, "min_rank": 29800}, {"year": 2024, "min_rank": 31500}],
                    "recommendation_reasons": ["C9顶尖高校，位次略有缺口，建议积极尝试冲击"],
                    "evidence_ids": ["ev-003"]
                }
            ]
        }
    ],
    "generated_at": "2026-07-02T10:00:00.000000Z"
}

MOCK_REPORT_EVIDENCE = [
    {
        "source_id": "ev-001",
        "source_type": "document",
        "title": "郑州大学2025年招生章程",
        "content": "郑州大学2025年软件工程在河南省投档线预计对应位次在35000名左右，选科限制为物理和化学。",
        "retrieved_at": "2026-07-02T10:00:00Z"
    },
    {
        "source_id": "ev-002",
        "source_type": "document",
        "title": "河南大学2025年投档线参考",
        "content": "河南大学计算机科学与技术在河南省往年平均录取位次约45000名，选科要求为物理。",
        "retrieved_at": "2026-07-02T10:00:00Z"
    },
    {
        "source_id": "ev-003",
        "source_type": "document",
        "title": "西安交通大学2025年招生章程",
        "content": "西安交通大学电子信息科学与技术在河南省历年最低位次在28000至33000名波动，选科要求物理和化学。",
        "retrieved_at": "2026-07-02T10:00:00Z"
    }
]
