import { Sparkles } from 'lucide-react'

interface Props {
  commentary: string | null
}

/**
 * 生成后 AI 点评卡片 (docs/backend-prd-v2.md §6.4 `condition_commentary`,
 * frontend-prd-v2.md §6.2「生成后 AI 点评卡片」)。位置：考生概况卡片下方。
 * 空字符串/null 时不展示该区块。
 */
export default function ConditionCommentaryCard({ commentary }: Props) {
  if (!commentary) return null

  return (
    <div className="wj-glass-card rounded-card px-4 py-3 flex items-start gap-2.5">
      <Sparkles className="w-4 h-4 text-[#A78BFA] flex-shrink-0 mt-0.5" />
      <p className="text-sm text-[#F1F5F9] leading-relaxed">{commentary}</p>
    </div>
  )
}
