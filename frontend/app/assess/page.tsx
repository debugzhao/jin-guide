'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import TopNav from '@/components/layout/TopNav'
import Button from '@/components/ui/Button'
import Card from '@/components/ui/Card'
import { useAppStore } from '@/lib/store'
import { useToastStore } from '@/components/ui/Toast'
import { cn } from '@/lib/utils'
import { AlertTriangle, TrendingUp, FileCheck } from 'lucide-react'

const assessSchema = z.object({
  province: z.string().min(1, '请选择省份'),
  batch: z.string().min(1, '请选择批次'),
  score: z.coerce.number().min(100, '分数不低于100').max(750, '分数不超过750'),
  rank: z.coerce.number().optional(),
  subjectType: z.enum(['physics', 'history'], { required_error: '请选择首选科目' }),
  electives: z.array(z.string()).optional(),
  gender: z.enum(['male', 'female'], { required_error: '请选择性别' }),
  hasPhysicalLimits: z.boolean(),
})

type AssessFormData = z.infer<typeof assessSchema>

const provinces = ['河南', '山东', '广东', '北京', '上海', '江苏', '浙江', '其他']
const electiveOptions = ['化学', '生物', '地理', '政治', '思想政治']

export default function AssessPage() {
  const router = useRouter()
  const { setAssessFormData } = useAppStore()
  const { addToast } = useToastStore()
  const [submitted, setSubmitted] = useState(false)
  const [selectedElectives, setSelectedElectives] = useState<string[]>([])

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<AssessFormData>({
    resolver: zodResolver(assessSchema),
    defaultValues: {
      batch: 'undergraduate',
      hasPhysicalLimits: false,
      electives: [],
    },
  })

  const hasPhysicalLimits = watch('hasPhysicalLimits')

  const toggleElective = (subject: string) => {
    const updated = selectedElectives.includes(subject)
      ? selectedElectives.filter((s) => s !== subject)
      : [...selectedElectives, subject]
    setSelectedElectives(updated)
    setValue('electives', updated)
  }

  const onSubmit = async (data: AssessFormData) => {
    try {
      setAssessFormData({
        province: data.province,
        batch: data.batch,
        score: data.score,
        rank: data.rank,
        subjects: [data.subjectType, ...selectedElectives],
        gender: data.gender,
        hasPhysicalLimits: data.hasPhysicalLimits,
      })
      setSubmitted(true)
    } catch {
      addToast('error', '提交失败，请重试')
    }
  }

  if (submitted) {
    return (
      <div className="min-h-screen bg-[#F8FAFC]">
        <TopNav title="快速测算" showBack backHref="/" />
        <div className="max-w-screen-md mx-auto px-4 py-6 space-y-4">
          <p className="text-sm text-[#64748B]">根据你的信息，初步分析结果如下</p>

          {/* Risk portrait card */}
          <Card className="p-4 space-y-4">
            <h2 className="text-base font-semibold text-[#0F172A]">风险画像</h2>

            <div className="flex items-center gap-3 p-3 bg-[#FFFBEB] rounded-btn">
              <AlertTriangle className="w-5 h-5 text-[#D97706]" />
              <div>
                <p className="text-xs text-[#64748B]">综合安全等级</p>
                <p className="text-sm font-semibold text-[#D97706]">中等</p>
              </div>
            </div>

            <div className="flex items-center gap-3 p-3 bg-[#EFF6FF] rounded-btn">
              <TrendingUp className="w-5 h-5 text-[#2563EB]" />
              <div>
                <p className="text-xs text-[#64748B]">预计可冲学校层级</p>
                <p className="text-sm font-semibold text-[#2563EB]">211 院校</p>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-[#64748B]">档案完整度</span>
                <span className="text-xs font-semibold text-[#0D9488]">40%</span>
              </div>
              <div className="h-2 bg-[#E2E8F0] rounded-full overflow-hidden">
                <div className="h-full w-2/5 bg-[#0D9488] rounded-full" />
              </div>
              <p className="text-xs text-[#94A3B8] mt-1">补全档案可大幅提升方案准确度</p>
            </div>
          </Card>

          <Card className="p-4 bg-[#EFF6FF] border-[#2563EB]">
            <div className="flex items-start gap-3">
              <FileCheck className="w-5 h-5 text-[#2563EB] flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-[#0F172A] mb-1">补全档案，生成三套方案</p>
                <p className="text-xs text-[#64748B]">填写更多信息（预算、城市偏好等），AI 将为你生成保守/均衡/进取三套完整志愿方案</p>
              </div>
            </div>
          </Card>

          <Button variant="primary" size="lg" onClick={() => router.push('/profile')}>
            补全档案，生成三套方案
          </Button>
          <button
            className="w-full text-sm text-[#64748B] py-2"
            onClick={() => router.push('/reports/demo')}
          >
            查看示例报告
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      <TopNav title="快速测算" showBack backHref="/" />
      <form onSubmit={handleSubmit(onSubmit)} className="max-w-screen-md mx-auto px-4 py-6 space-y-4">

        {/* Province */}
        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-[#0F172A]">基本信息</h3>

          <div>
            <label className="text-xs text-[#64748B] block mb-1">省份 <span className="text-[#DC2626]">*</span></label>
            <select
              {...register('province')}
              className="w-full border border-[#E2E8F0] rounded-btn px-3 py-2 text-sm text-[#0F172A] bg-white focus:outline-none focus:ring-2 focus:ring-[#1E40AF]"
            >
              <option value="">请选择省份</option>
              {provinces.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
            {errors.province && <p className="text-xs text-[#DC2626] mt-1">{errors.province.message}</p>}
          </div>

          <div>
            <label className="text-xs text-[#64748B] block mb-1">批次 <span className="text-[#DC2626]">*</span></label>
            <div className="flex gap-2">
              {[
                { value: 'undergraduate', label: '本科批' },
                { value: 'junior', label: '专科批' },
              ].map((option) => (
                <label key={option.value} className="flex-1">
                  <input type="radio" {...register('batch')} value={option.value} className="sr-only" />
                  <div className={cn(
                    'border rounded-btn py-2 text-sm text-center cursor-pointer transition-colors',
                    watch('batch') === option.value
                      ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                      : 'border-[#E2E8F0] text-[#64748B]'
                  )}>
                    {option.label}
                  </div>
                </label>
              ))}
            </div>
          </div>
        </Card>

        {/* Score */}
        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-[#0F172A]">成绩信息</h3>
          <div>
            <label className="text-xs text-[#64748B] block mb-1">分数 <span className="text-[#DC2626]">*</span></label>
            <input
              type="number"
              {...register('score')}
              placeholder="100 - 750"
              className="w-full border border-[#E2E8F0] rounded-btn px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E40AF]"
            />
            {errors.score && <p className="text-xs text-[#DC2626] mt-1">{errors.score.message}</p>}
          </div>
          <div>
            <label className="text-xs text-[#64748B] block mb-1">位次（选填，优先级高于分数）</label>
            <input
              type="number"
              {...register('rank')}
              placeholder="如：32680"
              className="w-full border border-[#E2E8F0] rounded-btn px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E40AF]"
            />
          </div>
        </Card>

        {/* Subjects */}
        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-[#0F172A]">选科信息</h3>
          <div>
            <label className="text-xs text-[#64748B] block mb-1">首选科目 <span className="text-[#DC2626]">*</span></label>
            <div className="flex gap-2">
              {[
                { value: 'physics', label: '物理' },
                { value: 'history', label: '历史' },
              ].map((option) => (
                <label key={option.value} className="flex-1">
                  <input type="radio" {...register('subjectType')} value={option.value} className="sr-only" />
                  <div className={cn(
                    'border rounded-btn py-2 text-sm text-center cursor-pointer transition-colors',
                    watch('subjectType') === option.value
                      ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                      : 'border-[#E2E8F0] text-[#64748B]'
                  )}>
                    {option.label}
                  </div>
                </label>
              ))}
            </div>
            {errors.subjectType && <p className="text-xs text-[#DC2626] mt-1">{errors.subjectType.message}</p>}
          </div>
          <div>
            <label className="text-xs text-[#64748B] block mb-1">再选科目（多选）</label>
            <div className="flex flex-wrap gap-2">
              {electiveOptions.map((subject) => (
                <button
                  key={subject}
                  type="button"
                  onClick={() => toggleElective(subject)}
                  className={cn(
                    'px-3 py-1.5 rounded-tag text-sm border transition-colors',
                    selectedElectives.includes(subject)
                      ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                      : 'border-[#E2E8F0] text-[#64748B]'
                  )}
                >
                  {subject}
                </button>
              ))}
            </div>
          </div>
        </Card>

        {/* Personal */}
        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-[#0F172A]">个人信息</h3>
          <div>
            <label className="text-xs text-[#64748B] block mb-1">性别 <span className="text-[#DC2626]">*</span></label>
            <div className="flex gap-2">
              {[
                { value: 'male', label: '男' },
                { value: 'female', label: '女' },
              ].map((option) => (
                <label key={option.value} className="flex-1">
                  <input type="radio" {...register('gender')} value={option.value} className="sr-only" />
                  <div className={cn(
                    'border rounded-btn py-2 text-sm text-center cursor-pointer transition-colors',
                    watch('gender') === option.value
                      ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                      : 'border-[#E2E8F0] text-[#64748B]'
                  )}>
                    {option.label}
                  </div>
                </label>
              ))}
            </div>
            {errors.gender && <p className="text-xs text-[#DC2626] mt-1">{errors.gender.message}</p>}
          </div>
          <div>
            <label className="text-xs text-[#64748B] block mb-2">是否有体检限制</label>
            <div className="flex gap-2">
              {[
                { value: true, label: '是' },
                { value: false, label: '否' },
              ].map((option) => (
                <button
                  key={String(option.value)}
                  type="button"
                  onClick={() => setValue('hasPhysicalLimits', option.value)}
                  className={cn(
                    'flex-1 border rounded-btn py-2 text-sm transition-colors',
                    hasPhysicalLimits === option.value
                      ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                      : 'border-[#E2E8F0] text-[#64748B]'
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </Card>

        <Button type="submit" variant="primary" size="lg" disabled={isSubmitting}>
          {isSubmitting ? '分析中...' : '查看风险画像'}
        </Button>
      </form>
    </div>
  )
}
