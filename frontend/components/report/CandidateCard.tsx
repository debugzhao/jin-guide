'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import Card from '@/components/ui/Card'
import Badge from '@/components/ui/Badge'
import { ChevronDown, ChevronUp, ExternalLink } from 'lucide-react'
import type { Candidate, BadgeVariant } from '@/types'

interface CandidateCardProps {
  candidate: Candidate
  rank: number
}

const tierToBadge: Record<string, BadgeVariant> = {
  rush: 'rush',
  target: 'target',
  safe: 'safe',
}

const tierLabel: Record<string, string> = {
  rush: '冲',
  target: '稳',
  safe: '保',
}

export default function CandidateCard({ candidate, rank }: CandidateCardProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <div className="w-7 h-7 rounded-full bg-[#EFF6FF] flex items-center justify-center text-xs font-semibold text-[#1E40AF] flex-shrink-0">
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-[#0F172A] truncate">
              {candidate.schoolName}
            </span>
            <Badge variant={tierToBadge[candidate.tier] ?? 'info'}>
              {tierLabel[candidate.tier]}
            </Badge>
            <span className="text-xs text-[#94A3B8]">{candidate.city}</span>
          </div>
          <div className="text-xs text-[#64748B] mb-2">
            {candidate.majorName} · {candidate.majorGroupCode}
          </div>
          {/* Safety score */}
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-[#64748B]">安全度</span>
            <div className="flex-1 h-1.5 bg-[#E2E8F0] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#0D9488] rounded-full"
                style={{ width: `${candidate.safetyScore}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-[#0D9488]">
              {candidate.safetyScore}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs text-[#64748B]">
            <span>综合评分 {candidate.overallScore}</span>
            <span>学费 {candidate.tuitionPerYear.toLocaleString('zh-CN')} 元/年</span>
          </div>
        </div>
      </div>

      {/* Expand toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="mt-3 flex items-center gap-1 text-xs text-[#1E40AF] w-full justify-center"
      >
        {expanded ? (
          <>收起详情 <ChevronUp className="w-3.5 h-3.5" /></>
        ) : (
          <>查看详情 <ChevronDown className="w-3.5 h-3.5" /></>
        )}
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-[#E2E8F0] space-y-3">
          <div>
            <span className="text-xs font-medium text-[#0F172A]">选科要求：</span>
            <span className="text-xs text-[#64748B]">{candidate.subjectRequirements}</span>
          </div>
          <div>
            <p className="text-xs font-medium text-[#0F172A] mb-1">推荐理由：</p>
            <ul className="space-y-1">
              {candidate.reasons.map((reason, i) => (
                <li key={i} className="text-xs text-[#64748B] flex items-start gap-1">
                  <span className="text-[#0D9488] mt-0.5">·</span>
                  {reason}
                </li>
              ))}
            </ul>
          </div>
          {candidate.dataSourceUrl && (
            <a
              href={candidate.dataSourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-[#1E40AF]"
            >
              查看数据来源 <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      )}
    </Card>
  )
}
