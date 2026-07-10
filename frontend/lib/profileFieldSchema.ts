/**
 * 建档字段 schema：字段 key → 控件类型/文案/选项的映射，供 FieldControl 渲染。
 *
 * 字段出场顺序由后端 `POST /profile/field-check` 响应里的 `next_fields` 决定
 * （`backend/app/api/v1/profile.py::_FIELD_ORDER`，纯配置驱动、零 LLM 调用），
 * 这里只镜像同一份顺序作为前端未收到响应前的初始队列，真正的推进节奏以后端
 * 返回值为准（docs/frontend-prd-v2.md §6.1「确定性逻辑与 Agent 边界」）。
 */

export type FieldControlType =
  | 'select'
  | 'radio-group'
  | 'number-input'
  | 'subject-picker'
  | 'boolean-with-detail'
  | 'plan-cards'
  | 'chip-multiselect'

export interface FieldOption {
  value: string
  label: string
}

export interface FieldSchemaEntry {
  key: string
  /** AI 消息气泡文案 */
  question: string
  controlType: FieldControlType
  /** 学生基础信息 = 必填；其余 = 建议（docs/frontend-prd-v2.md §6.1 字段清单表） */
  required: boolean
  options?: FieldOption[]
  placeholder?: string
  helpText?: string
}

// 与 backend/app/api/v1/profile.py::_FIELD_ORDER 保持一致的初始顺序
export const PROFILE_FIELD_ORDER = [
  'province',
  'batch',
  'score',
  'rank',
  'subjects',
  'gender',
  'has_physical_limits',
  'family_budget',
  'risk_style',
  'city_prefs',
  'major_prefs',
] as const

export type ProfileFieldKey = (typeof PROFILE_FIELD_ORDER)[number]

export const PROVINCES = [
  '北京', '上海', '天津', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
  '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
  '广东', '海南', '四川', '贵州', '云南', '陕西', '甘肃', '青海', '内蒙古',
  '广西', '西藏', '新疆', '宁夏',
]
export const OTHER_SUBJECTS = ['化学', '生物', '地理', '政治']
export const MEDICAL_RESTRICTIONS = ['色觉异常（色盲/色弱）', '视力受限', '听力障碍', '肢体残疾']
export const CITIES = [
  '北京', '上海', '广州', '深圳', '成都', '杭州', '武汉', '西安', '南京', '重庆',
  '天津', '苏州', '长沙', '合肥', '郑州', '厦门',
]
export const MAJOR_GROUPS = [
  '计算机/软件', '数学/统计', '电子/通信', '机械/自动化', '医学/药学',
  '经济/金融', '法学', '中文/新闻', '外语', '艺术/设计', '师范/教育', '农林', '其他',
]

export const PROFILE_FIELD_SCHEMA: Record<ProfileFieldKey, FieldSchemaEntry> = {
  province: {
    key: 'province',
    question: '你在哪个省份参加高考？',
    controlType: 'select',
    required: true,
    options: PROVINCES.map((p) => ({ value: p, label: p })),
    placeholder: '请选择省份',
  },
  batch: {
    key: 'batch',
    question: '目标批次是？',
    controlType: 'radio-group',
    required: true,
    options: [
      { value: '本科批', label: '本科批' },
      { value: '专科批', label: '专科批' },
    ],
  },
  score: {
    key: 'score',
    question: '高考分数是多少？',
    controlType: 'number-input',
    required: true,
    placeholder: '例：612',
  },
  rank: {
    key: 'rank',
    question: '知道全省位次吗？',
    controlType: 'number-input',
    required: false,
    placeholder: '例：32680',
    helpText: '选填，但填写后推荐结果会更准确',
  },
  subjects: {
    key: 'subjects',
    question: '你的选考科目组合是？',
    controlType: 'subject-picker',
    required: true,
  },
  gender: {
    key: 'gender',
    question: '性别是？',
    controlType: 'radio-group',
    required: true,
    options: [
      { value: '男', label: '男' },
      { value: '女', label: '女' },
      { value: '不限', label: '不限' },
    ],
  },
  has_physical_limits: {
    key: 'has_physical_limits',
    question: '是否存在体检限制条件（如色觉异常、视力受限等）？',
    controlType: 'boolean-with-detail',
    required: true,
    options: MEDICAL_RESTRICTIONS.map((m) => ({ value: m, label: m })),
    helpText: '会影响部分专业的报考资格，如医学、化学类',
  },
  family_budget: {
    key: 'family_budget',
    question: '家庭年学费预算上限是多少？',
    controlType: 'number-input',
    required: false,
    placeholder: '例：8000（元/年）',
    helpText: '建议填写，不填也可以先生成基础版报告',
  },
  risk_style: {
    key: 'risk_style',
    question: '志愿策略偏好？',
    controlType: 'plan-cards',
    required: false,
    options: [
      { value: 'conservative', label: '保守型 · 以稳为主，优先确保录取' },
      { value: 'balanced', label: '均衡型 · 冲稳保均衡配置，综合最优' },
      { value: 'aggressive', label: '进取型 · 优先冲高，接受一定风险' },
    ],
  },
  city_prefs: {
    key: 'city_prefs',
    question: '有倾向的城市吗？',
    controlType: 'chip-multiselect',
    required: false,
    options: CITIES.map((c) => ({ value: c, label: c })),
    helpText: '可多选，不选则不限地域',
  },
  major_prefs: {
    key: 'major_prefs',
    question: '感兴趣的专业方向？',
    controlType: 'chip-multiselect',
    required: false,
    options: MAJOR_GROUPS.map((m) => ({ value: m, label: m })),
    helpText: '可多选，不选则由 AI 综合评估',
  },
}
