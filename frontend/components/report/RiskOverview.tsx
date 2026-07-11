import { cn } from '@/lib/utils'
import Card from '@/components/ui/Card'
import { AlertTriangle, AlertCircle, CheckCircle, Info } from 'lucide-react'
import type { RiskLevel, RiskItem } from '@/types'

interface RiskOverviewProps {
  overallRisk: RiskLevel
  riskItems: RiskItem[]
}

const riskConfig: Record<RiskLevel, {
  label: string
  bg: string
  text: string
  border: string
  icon: React.ComponentType<{ className?: string }>
}> = {
  high: {
    label: '高风险',
    bg: 'bg-[rgba(242,169,169,0.12)]',
    text: 'text-[#F2A9A9]',
    border: 'border-[rgba(242,169,169,0.32)]',
    icon: AlertCircle,
  },
  medium: {
    label: '中等风险',
    bg: 'bg-[rgba(239,196,138,0.12)]',
    text: 'text-[#EFC48A]',
    border: 'border-[rgba(239,196,138,0.32)]',
    icon: AlertTriangle,
  },
  low: {
    label: '低风险',
    bg: 'bg-[rgba(143,224,183,0.12)]',
    text: 'text-[#8FE0B7]',
    border: 'border-[rgba(143,224,183,0.32)]',
    icon: CheckCircle,
  },
  info: {
    label: '提示',
    bg: 'bg-[rgba(169,180,245,0.12)]',
    text: 'text-[#A9B4F5]',
    border: 'border-[rgba(169,180,245,0.32)]',
    icon: Info,
  },
}

const itemIconMap: Record<RiskLevel, React.ComponentType<{ className?: string }>> = {
  high: AlertCircle,
  medium: AlertTriangle,
  low: CheckCircle,
  info: Info,
}

const itemColorMap: Record<RiskLevel, string> = {
  high: 'text-[#F2A9A9]',
  medium: 'text-[#EFC48A]',
  low: 'text-[#8FE0B7]',
  info: 'text-[#A9B4F5]',
}

export default function RiskOverview({ overallRisk, riskItems }: RiskOverviewProps) {
  const config = riskConfig[overallRisk] ?? riskConfig.info
  const OverallIcon = config.icon

  return (
    <Card className="p-0 overflow-hidden">
      {/* Overall risk header */}
      <div className={cn('px-4 py-3 flex items-center gap-3', config.bg)}>
        <OverallIcon className={cn('w-6 h-6', config.text)} />
        <div>
          <p className="text-xs text-[#9CA3C4]">整体风险等级</p>
          <p className={cn('text-lg font-bold', config.text)}>{config.label}</p>
        </div>
      </div>
      {/* Risk items */}
      {riskItems.length > 0 && (
        <div className="p-4 space-y-2">
          {riskItems.map((item, i) => {
            const ItemIcon = itemIconMap[item.level] ?? Info
            return (
              <div key={i} className="flex items-start gap-2">
                <ItemIcon className={cn('w-4 h-4 mt-0.5 flex-shrink-0', itemColorMap[item.level] ?? itemColorMap.info)} />
                <span className="text-sm text-[#F1F5F9]">{item.description}</span>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
