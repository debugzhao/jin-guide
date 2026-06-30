'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Share2, Download } from 'lucide-react'
import TopNav from '@/components/layout/TopNav'
import RiskOverview from '@/components/report/RiskOverview'
import PlanTabs from '@/components/report/PlanTabs'
import CandidateCard from '@/components/report/CandidateCard'
import { useAppStore } from '@/lib/store'
import type { Candidate, PlanType, Report } from '@/types'

const MOCK_REPORT: Report = {
  id: 'demo-report',
  createdAt: '2026-06-30',
  province: '湖南',
  score: 587,
  rank: 12340,
  subjects: ['物理', '化学', '历史'],
  overallRisk: 'medium',
  riskItems: [
    { level: 'high', description: '你的位次处于目标院校录取边缘区间（±5000），录取风险较高' },
    { level: 'medium', description: '所选 3 所"冲"志愿历年录取人数波动较大，存在不确定性' },
    { level: 'low', description: '保底院校稳定，近 3 年最低位次与你差距超过 1 万，安全系数高' },
    { level: 'info', description: '建议关注专业调剂条款，4 所院校不服从调剂将直接退档' },
  ],
  plans: {
    conservative: [
      {
        id: 'c1', schoolName: '中南大学', city: '长沙', tier: 'rush',
        majorName: '计算机科学与技术', majorGroupCode: '003组',
        safetyScore: 62, overallScore: 88, tuitionPerYear: 6000,
        subjectRequirements: '物理必选',
        reasons: ['近 3 年录取位次稳定在 10000-14000 区间', '计算机学院国家重点实验室，就业率 95%+', '长沙生活成本低，性价比高'],
      },
      {
        id: 'c2', schoolName: '湖南大学', city: '长沙', tier: 'target',
        majorName: '软件工程', majorGroupCode: '005组',
        safetyScore: 78, overallScore: 85, tuitionPerYear: 6000,
        subjectRequirements: '物理必选',
        reasons: ['211 院校，录取位次 13000-16000，与你匹配度高', '和华为、腾讯有校企合作项目', '本省院校，无外省竞争压力'],
      },
      {
        id: 'c3', schoolName: '中南林业科技大学', city: '长沙', tier: 'safe',
        majorName: '数据科学与大数据技术', majorGroupCode: '002组',
        safetyScore: 93, overallScore: 72, tuitionPerYear: 5200,
        subjectRequirements: '不限',
        reasons: ['近 3 年最低录取位次 21000，保底安全', '新兴专业，课程设置较新', '留长沙就业方便'],
      },
    ],
    balanced: [
      {
        id: 'b1', schoolName: '北京邮电大学', city: '北京', tier: 'rush',
        majorName: '人工智能', majorGroupCode: '101组',
        safetyScore: 45, overallScore: 92, tuitionPerYear: 6000,
        subjectRequirements: '物理必选',
        reasons: ['顶级通信/AI 院校，就业竞争力极强', '近 3 年录取位次约 8000-11000，有一定难度', '北京学习资源丰富，实习机会多'],
        dataSourceUrl: 'https://www.bupt.edu.cn',
      },
      {
        id: 'b2', schoolName: '电子科技大学', city: '成都', tier: 'rush',
        majorName: '电子信息工程', majorGroupCode: '003组',
        safetyScore: 50, overallScore: 91, tuitionPerYear: 6000,
        subjectRequirements: '物理必选',
        reasons: ['985 院校，电子信息领域顶尖', '近 3 年录取位次 9000-12500，你位次处于边缘', '成都互联网产业快速发展'],
      },
      {
        id: 'b3', schoolName: '中南大学', city: '长沙', tier: 'target',
        majorName: '软件工程', majorGroupCode: '006组',
        safetyScore: 72, overallScore: 88, tuitionPerYear: 6000,
        subjectRequirements: '物理必选',
        reasons: ['211 院校，本地就业优先', '录取位次 11000-15000，与你匹配'],
      },
      {
        id: 'b4', schoolName: '湖南师范大学', city: '长沙', tier: 'safe',
        majorName: '计算机科学与技术', majorGroupCode: '001组',
        safetyScore: 90, overallScore: 70, tuitionPerYear: 5000,
        subjectRequirements: '不限',
        reasons: ['省内师范类院校，位次 19000-22000，稳定保底'],
      },
    ],
    aggressive: [
      {
        id: 'a1', schoolName: '武汉大学', city: '武汉', tier: 'rush',
        majorName: '计算机科学与技术', majorGroupCode: '005组',
        safetyScore: 28, overallScore: 96, tuitionPerYear: 6000,
        subjectRequirements: '物理+化学',
        reasons: ['985 顶校，录取位次约 6000-9000，你位次差距较大', '高风险高回报，适合心态稳健的考生'],
      },
      {
        id: 'a2', schoolName: '华中科技大学', city: '武汉', tier: 'rush',
        majorName: '人工智能', majorGroupCode: '009组',
        safetyScore: 32, overallScore: 94, tuitionPerYear: 6000,
        subjectRequirements: '物理必选',
        reasons: ['985 工科强校，AI 专业近 2 年新增，数据波动大', '录取位次区间 7500-11000，存在机会'],
      },
      {
        id: 'a3', schoolName: '中南大学', city: '长沙', tier: 'target',
        majorName: '计算机科学与技术', majorGroupCode: '003组',
        safetyScore: 65, overallScore: 88, tuitionPerYear: 6000,
        subjectRequirements: '物理必选',
        reasons: ['录取位次 10000-14000，你有机会冲上'],
      },
      {
        id: 'a4', schoolName: '湖南大学', city: '长沙', tier: 'safe',
        majorName: '数学与应用数学', majorGroupCode: '001组',
        safetyScore: 82, overallScore: 80, tuitionPerYear: 5500,
        subjectRequirements: '不限',
        reasons: ['211 院校保底，位次 15000-18000 区间'],
      },
    ],
  },
}

export default function ReportDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const { currentTab, setCurrentTab } = useAppStore()

  const report = MOCK_REPORT
  const candidates: Candidate[] = report.plans[currentTab as PlanType] ?? []

  const handleShare = async () => {
    try {
      await navigator.share({ title: '我的高考志愿方案', url: window.location.href })
    } catch {}
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      <TopNav
        title="志愿方案"
        showBack
        onBack={() => router.push('/')}
        rightSlot={
          <div className="flex items-center gap-2">
            <button
              onClick={handleShare}
              className="p-2 rounded-btn text-[#64748B] hover:text-[#0F172A] hover:bg-[#F1F5F9]"
            >
              <Share2 className="w-4.5 h-4.5" />
            </button>
            <button className="p-2 rounded-btn text-[#64748B] hover:text-[#0F172A] hover:bg-[#F1F5F9]">
              <Download className="w-4.5 h-4.5" />
            </button>
          </div>
        }
      />

      <main className="max-w-screen-md mx-auto px-4 py-5 space-y-4">
        {/* Meta info */}
        <div className="flex items-center gap-3 text-xs text-[#64748B]">
          <span>{report.province} · {report.score} 分</span>
          <span>全省第 {report.rank?.toLocaleString('zh-CN')} 名</span>
          <span>{report.subjects.join('/')} 选科</span>
          <span className="ml-auto">{report.createdAt}</span>
        </div>

        {/* Risk overview */}
        <RiskOverview overallRisk={report.overallRisk} riskItems={report.riskItems} />

        {/* Plan tabs */}
        <PlanTabs currentTab={currentTab as PlanType} onChange={setCurrentTab} />

        {/* Plan desc */}
        <div className="text-xs text-[#64748B] px-1">
          {{
            conservative: '以稳为主，优先确保录取成功率，适合求稳的考生',
            balanced: '冲稳保均衡分配，综合性价比最高，AI 推荐方案',
            aggressive: '优先冲击高层次院校，适合心态好、不怕复读的考生',
          }[currentTab as PlanType]}
        </div>

        {/* Candidate cards */}
        <div className="space-y-3 pb-6">
          {candidates.map((c, i) => (
            <CandidateCard key={c.id} candidate={c} rank={i + 1} />
          ))}
        </div>
      </main>
    </div>
  )
}
