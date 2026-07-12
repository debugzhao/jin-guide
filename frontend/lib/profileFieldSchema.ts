/**
 * 建档字段 schema：字段 key → 表单控件类型/标签/选项的映射，供
 * `ProfileCaptureCard` 渲染成一张分组卡片（docs/wenjin-agent-prototype.html
 * 第 1051-1093 行「基础建档信息」卡片是当前交互事实源：所有必填字段一起
 * 展示在同一张 `.field-grid` 两列网格卡片里，不是逐条对话气泡）。
 *
 * 字段跳过逻辑仍然纯本地计算（专科批跳过本科限定字段等），矛盾检测复用
 * 后端 `POST /profile/field-check`（backend/app/api/v1/profile.py::_FIELD_ORDER），
 * 只是触发时机从"每填一个字段查一次"改为"点击卡片底部确认按钮时统一查"。
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
  /** 网格卡片里的字段标签 */
  label: string
  controlType: FieldControlType
  /** 学生基础信息 = 必填；其余 = 建议（docs/frontend-prd-v2.md §6.1 字段清单表） */
  required: boolean
  options?: FieldOption[]
  placeholder?: string
  helpText?: string
}

// 与 backend/app/api/v1/profile.py::_FIELD_ORDER 保持一致
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

// 必填字段渲染进「基础建档信息」卡片；建议字段改由底部自然语言输入框补充
// (docs/wenjin-agent-prototype.html sendConversation()/preferenceFormHtml())
export const REQUIRED_FIELD_KEYS: ProfileFieldKey[] = [
  'province', 'batch', 'score', 'rank', 'subjects', 'gender', 'has_physical_limits',
]

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
    label: '省份',
    controlType: 'select',
    required: true,
    options: PROVINCES.map((p) => ({ value: p, label: p })),
    placeholder: '请选择省份',
  },
  batch: {
    key: 'batch',
    label: '批次',
    controlType: 'radio-group',
    required: true,
    options: [
      { value: '本科批', label: '本科批' },
      { value: '专科批', label: '专科批' },
    ],
  },
  score: {
    key: 'score',
    label: '高考分数',
    controlType: 'number-input',
    required: true,
    placeholder: '例：612',
  },
  rank: {
    key: 'rank',
    label: '全省位次',
    controlType: 'number-input',
    required: false,
    placeholder: '例：32680',
    helpText: '分数和位次至少填一个，同时有位次时优先用位次匹配',
  },
  subjects: {
    key: 'subjects',
    label: '选考科目',
    controlType: 'subject-picker',
    required: true,
  },
  gender: {
    key: 'gender',
    label: '性别',
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
    label: '体检限制',
    controlType: 'boolean-with-detail',
    required: true,
    options: MEDICAL_RESTRICTIONS.map((m) => ({ value: m, label: m })),
    helpText: '如色觉异常、视力受限等，会影响部分专业报考资格',
  },
  family_budget: {
    key: 'family_budget',
    label: '家庭年学费预算',
    controlType: 'number-input',
    required: false,
    placeholder: '例：8000（元/年）',
  },
  risk_style: {
    key: 'risk_style',
    label: '志愿策略偏好',
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
    label: '倾向城市',
    controlType: 'chip-multiselect',
    required: false,
    options: CITIES.map((c) => ({ value: c, label: c })),
  },
  major_prefs: {
    key: 'major_prefs',
    label: '感兴趣的专业方向',
    controlType: 'chip-multiselect',
    required: false,
    options: MAJOR_GROUPS.map((m) => ({ value: m, label: m })),
  },
}
