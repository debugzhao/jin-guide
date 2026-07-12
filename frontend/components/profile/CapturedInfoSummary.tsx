interface CapturedInfoSummaryProps {
  values: Record<string, unknown>
}

const FIELD_LABELS: [string, string][] = [
  ['province', '省份'],
  ['batch', '批次'],
  ['score', '高考分数'],
  ['rank', '全省位次'],
  ['subjects', '选考科目'],
  ['gender', '性别'],
]

function formatValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return '未填写'
  if (Array.isArray(value)) return value.length ? value.join('、') : '不限'
  return String(value)
}

/**
 * 「已采集信息」卡片 —— Agent 从上方 Generative UI 表单里沉淀出的结构化档案
 * 摘要，小方块网格展示（docs/wenjin-agent-prototype.html 第 1096-1107 行）。
 */
export default function CapturedInfoSummary({ values }: CapturedInfoSummaryProps) {
  return (
    <div className="bg-[#EFF6FF] border border-[#BFDBFE] rounded-2xl rounded-tl-sm px-4 py-3 max-w-[96%] space-y-2">
      <div className="text-xs text-[#64748B]">已采集信息</div>
      <p className="text-sm text-[#0F172A]">
        这些不是手动发送的聊天内容，而是从上方基础建档信息卡片里沉淀出的结构化档案。
      </p>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(110px,1fr))] gap-2">
        {FIELD_LABELS.map(([key, label]) => (
          <div key={key} className="border border-[#E2E8F0] rounded-lg bg-[#F8FAFC] p-2.5">
            <span className="text-xs text-[#64748B]">{label}</span>
            <strong className="block text-sm text-[#0F172A] mt-0.5">{formatValue(values[key])}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}
