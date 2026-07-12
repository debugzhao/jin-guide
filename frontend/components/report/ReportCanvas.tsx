'use client'

import RiskOverview from './RiskOverview'
import PlanTabs from './PlanTabs'
import CandidateCard from './CandidateCard'
import ConditionCommentaryCard from './ConditionCommentaryCard'
import DecisionReplayCard from './DecisionReplayCard'
import { useAppStore } from '@/lib/store'
import type { PlanType } from '@/types'
import type { ReportViewModel } from '@/lib/reportMapping'

const PLAN_DESC: Record<string, string> = {
  conservative: '以稳为主，优先确保录取成功率，适合求稳的考生',
  balanced: '冲稳保均衡分配，综合性价比最高，AI 推荐方案',
  aggressive: '优先冲击高层次院校，适合心态好、不怕复读的考生',
}

interface ReportCanvasProps {
  report: ReportViewModel
}

/**
 * 报告画布主体：考生概况 / AI 条件点评 / 风险总览 / 决策回放 / 三套方案 Tab +
 * 候选卡片。同时被 `/`（实时报告面板）和 `/reports/[id]`（报告工作台）复用
 * （frontend-prd-v2.md §6.1「与 §6.2 报告工作台的关系」）。
 */
export default function ReportCanvas({ report }: ReportCanvasProps) {
  const { currentTab, setCurrentTab } = useAppStore()

  const activeTab = (report.plansMap[currentTab] ? currentTab : 'balanced') as PlanType
  const candidates = report.plansMap[activeTab] ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-xs text-[#64748B] flex-wrap">
        {report.province && <span>{report.province} · {report.score} 分</span>}
        {report.rank && <span>全省第 {report.rank.toLocaleString('zh-CN')} 名</span>}
        {report.subjects && <span>{report.subjects.join('/')} 选科</span>}
        <span className="ml-auto">{report.createdAt.slice(0, 10)}</span>
      </div>

      <ConditionCommentaryCard commentary={report.conditionCommentary} />

      <RiskOverview overallRisk={report.overallRisk} riskItems={report.riskItems} />

      <DecisionReplayCard runSummary={report.runSummary} />

      <PlanTabs currentTab={activeTab} onChange={setCurrentTab} />
      <div className="text-xs text-[#64748B] px-1">{PLAN_DESC[activeTab] || ''}</div>

      {candidates.length > 0 ? (
        <div className="space-y-3">
          {candidates.map((c, i) => (
            <CandidateCard key={c.id} candidate={c} rank={i + 1} />
          ))}
        </div>
      ) : (
        <div className="py-10 text-center text-sm text-[#94A3B8]">暂无候选院校数据</div>
      )}
    </div>
  )
}
