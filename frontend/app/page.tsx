'use client'

import { useRouter } from 'next/navigation'
import { Compass, ClipboardCheck, BarChart2 } from 'lucide-react'
import EntryCard from '@/components/entry/EntryCard'
import Button from '@/components/ui/Button'

export default function HomePage() {
  const router = useRouter()

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      {/* Header */}
      <header className="bg-white border-b border-[#E2E8F0] px-4 py-4">
        <div className="max-w-screen-md mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-[#1E40AF]">问津 Agent</h1>
            <p className="text-xs text-[#64748B] mt-0.5">AI 志愿决策助理，帮你稳上心仪大学</p>
          </div>
          <Button variant="ghost" size="sm">
            登录
          </Button>
        </div>
      </header>

      {/* Entry cards */}
      <main className="max-w-screen-md mx-auto px-4 py-6 space-y-4">
        <p className="text-sm text-[#64748B] mb-2">请选择你的需求，开始志愿分析</p>

        <EntryCard
          icon={Compass}
          title="我还没思路"
          description="刚出分，帮你生成三套方案"
          materials="省份 + 分数/位次 + 选科"
          estimatedTime="约 15 分钟"
          actionLabel="开始分析"
          onClick={() => router.push('/assess')}
        />

        <EntryCard
          icon={ClipboardCheck}
          title="我已有志愿表"
          description="帮你检查风险和盲区"
          materials="已填好的志愿草稿"
          estimatedTime="约 5 分钟"
          actionLabel="上传志愿表"
          onClick={() => router.push('/assess')}
        />

        <EntryCard
          icon={BarChart2}
          title="我想比较学校/专业"
          description="Phase 2，即将推出"
          materials="—"
          estimatedTime="—"
          actionLabel="即将推出"
          disabled
          disabledReason="功能开发中，敬请期待"
        />
      </main>
    </div>
  )
}
