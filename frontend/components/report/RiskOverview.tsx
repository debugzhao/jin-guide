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
    bg: 'bg-[#FEF2F2]',
    text: 'text-[#DC2626]',
    border: 'border-[#FECACA]',
    icon: AlertCircle,
  },
  medium: {
    label: '中等风险',
    bg: 'bg-[#FFFBEB]',
    text: 'text-[#D97706]',
    border: 'border-[#FDE68A]',
    icon: AlertTriangle,
  },
  low: {
    label: '低风险',
    bg: 'bg-[#F0FDF4]',
    text: 'text-[#16A34A]',
    border: 'border-[#BBF7D0]',
    icon: CheckCircle,
  },
  info: {
    label: '提示',
    bg: 'bg-[#EFF6FF]',
    text: 'text-[#2563EB]',
    border: 'border-[#BFDBFE]',
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
  high: 'text-[#DC2626]',
  medium: 'text-[#D97706]',
  low: 'text-[#16A34A]',
  info: 'text-[#2563EB]',
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
          <p className="text-xs text-[#64748B]">整体风险等级</p>
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
                <span className="text-sm text-[#0F172A]">{item.description}</span>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
