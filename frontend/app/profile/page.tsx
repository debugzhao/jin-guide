'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import TopNav from '@/components/layout/TopNav'
import ProfileStepper from '@/components/profile/ProfileStepper'
import Button from '@/components/ui/Button'
import { api } from '@/lib/api'
import { useAppStore } from '@/lib/store'
import type { ProfileData } from '@/types'

const STEPS = [
  { label: '考生基本信息', required: true },
  { label: '选科与身体条件', required: true },
  { label: '地区偏好', required: false },
  { label: '专业意向', required: false },
  { label: '风险与预算偏好', required: false },
  { label: '确认提交', required: true },
]

const PROVINCES = ['北京', '上海', '天津', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
  '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
  '广东', '海南', '四川', '贵州', '云南', '陕西', '甘肃', '青海', '内蒙古',
  '广西', '西藏', '新疆', '宁夏']
const SUBJECTS = ['语文', '数学', '英语', '物理', '化学', '生物', '历史', '地理', '政治']
const MAJOR_GROUPS = ['计算机/软件', '数学/统计', '电子/通信', '机械/自动化', '医学/药学',
  '经济/金融', '法学', '中文/新闻', '外语', '艺术/设计', '师范/教育', '农林', '其他']
const CITIES = ['北京', '上海', '广州', '深圳', '成都', '杭州', '武汉', '西安', '南京', '重庆',
  '天津', '苏州', '长沙', '合肥', '郑州', '厦门']

const step1Schema = z.object({
  province: z.string().min(1, '请选择省份'),
  batch: z.string().min(1, '请选择批次'),
  score: z.number({ invalid_type_error: '请输入分数' }).int().min(0).max(750),
  rank: z.number({ invalid_type_error: '请输入位次' }).int().min(1).optional(),
})

type Step1 = z.infer<typeof step1Schema>

export default function ProfilePage() {
  const router = useRouter()
  const { setProfileId } = useAppStore()
  const [step, setStep] = useState(1)
  const [formData, setFormData] = useState<Partial<ProfileData>>({})
  const [loading, setLoading] = useState(false)

  // Step 2 local state
  const [subjects, setSubjects] = useState<string[]>([])
  const [gender, setGender] = useState<string>('')
  const [hasPhysicalLimits, setHasPhysicalLimits] = useState(false)

  // Step 3 local state
  const [preferredCities, setPreferredCities] = useState<string[]>([])
  const [excludedCities, setExcludedCities] = useState<string[]>([])
  const [acceptsOutOfProvince, setAcceptsOutOfProvince] = useState(true)

  // Step 4 local state
  const [interestedMajors, setInterestedMajors] = useState<string[]>([])
  const [excludedMajors, setExcludedMajors] = useState<string[]>([])

  // Step 5 local state
  const [riskStyle, setRiskStyle] = useState<ProfileData['riskStyle']>('balanced')
  const [budgetRange, setBudgetRange] = useState<string>('1-2万/年')

  const { register, handleSubmit, formState: { errors } } = useForm<Step1>({
    resolver: zodResolver(step1Schema),
  })

  const toggleItem = (arr: string[], item: string, setArr: (v: string[]) => void) => {
    setArr(arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item])
  }

  const onStep1Submit = (data: Step1) => {
    setFormData(prev => ({ ...prev, ...data }))
    setStep(2)
  }

  const goNext = () => setStep(s => s + 1)
  const goBack = () => setStep(s => s - 1)

  const handleFinalSubmit = async () => {
    const payload: ProfileData = {
      ...formData as ProfileData,
      subjects,
      gender,
      hasPhysicalLimits,
      preferredCities,
      excludedCities,
      acceptsOutOfProvince,
      interestedMajors,
      excludedMajors,
      riskStyle,
      budgetRange,
    }
    setLoading(true)
    try {
      const { profileId } = await api.createProfile(payload)
      setProfileId(profileId)
      const { runId } = await api.generateReport({ profileId })
      router.push(`/reports/generating?runId=${runId}`)
    } catch {
      router.push(`/reports/generating?runId=demo-run`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="wj-profile-shell min-h-screen bg-[#F8FAFC]">
      <TopNav title="建档问诊" showBack onBack={() => step > 1 ? goBack() : router.back()} />

      <main className="wj-profile-main max-w-screen-md mx-auto px-4 py-6">
        <aside className="wj-profile-sidebar">
          <ProfileStepper steps={STEPS} currentStep={step} />
        </aside>

        <section className="wj-profile-panel">

        {/* Step 1: 基本信息 */}
        {step === 1 && (
          <form onSubmit={handleSubmit(onStep1Submit)} className="wj-profile-form space-y-5">
            <div>
              <label className="wj-field-label block text-sm font-medium text-[#0F172A] mb-1.5">省份</label>
              <select
                {...register('province')}
                className="wj-select w-full border border-[#E2E8F0] rounded-btn px-3 py-2.5 text-sm bg-white text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-[#1E40AF]/30"
              >
                <option value="">请选择省份</option>
                {PROVINCES.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
              {errors.province && <p className="text-xs text-[#DC2626] mt-1">{errors.province.message}</p>}
            </div>

            <div>
              <label className="wj-field-label block text-sm font-medium text-[#0F172A] mb-1.5">批次</label>
              <div className="wj-choice-row flex gap-2">
                {['本科一批', '本科二批', '专科批'].map(b => (
                  <label key={b} className="wj-choice-card flex-1 flex items-center justify-center gap-1.5 border border-[#E2E8F0] rounded-btn py-2.5 text-sm cursor-pointer has-[:checked]:border-[#1E40AF] has-[:checked]:bg-[#EFF6FF] has-[:checked]:text-[#1E40AF]">
                    <input type="radio" {...register('batch')} value={b} className="sr-only" />
                    {b}
                  </label>
                ))}
              </div>
              {errors.batch && <p className="text-xs text-[#DC2626] mt-1">{errors.batch.message}</p>}
            </div>

            <div>
              <label className="wj-field-label block text-sm font-medium text-[#0F172A] mb-1.5">高考分数</label>
              <input
                type="number"
                {...register('score', { valueAsNumber: true })}
                placeholder="例：587"
                className="wj-input w-full border border-[#E2E8F0] rounded-btn px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E40AF]/30"
              />
              {errors.score && <p className="text-xs text-[#DC2626] mt-1">{errors.score.message}</p>}
            </div>

            <div>
              <label className="wj-field-label block text-sm font-medium text-[#0F172A] mb-1.5">
                全省位次 <span className="wj-field-help text-[#94A3B8] font-normal">（选填，更准确）</span>
              </label>
              <input
                type="number"
                {...register('rank', { valueAsNumber: true })}
                placeholder="例：12345"
                className="wj-input w-full border border-[#E2E8F0] rounded-btn px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E40AF]/30"
              />
            </div>

            <div className="wj-actions">
              <Button type="submit" className="w-full mt-2">下一步</Button>
            </div>
          </form>
        )}

        {/* Step 2: 选科与身体条件 */}
        {step === 2 && (
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">选考科目（可多选）</label>
              <div className="flex flex-wrap gap-2">
                {SUBJECTS.map(s => (
                  <button
                    key={s}
                    onClick={() => toggleItem(subjects, s, setSubjects)}
                    className={`px-3 py-1.5 rounded-tag text-sm border transition-colors ${
                      subjects.includes(s)
                        ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">性别</label>
              <div className="flex gap-3">
                {['男', '女', '不限'].map(g => (
                  <button
                    key={g}
                    onClick={() => setGender(g)}
                    className={`flex-1 py-2.5 rounded-btn text-sm border transition-colors ${
                      gender === g
                        ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {g}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">是否有身体限制条件</label>
              <p className="text-xs text-[#64748B] mb-2">如色觉异常、听力障碍等，影响部分专业报考资格</p>
              <div className="flex gap-3">
                {[{ label: '有限制', value: true }, { label: '无限制', value: false }].map(opt => (
                  <button
                    key={String(opt.value)}
                    onClick={() => setHasPhysicalLimits(opt.value)}
                    className={`flex-1 py-2.5 rounded-btn text-sm border transition-colors ${
                      hasPhysicalLimits === opt.value
                        ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="wj-actions flex gap-3 pt-2">
              <Button variant="outline" className="flex-1" onClick={goBack}>上一步</Button>
              <Button className="flex-1" onClick={goNext}>下一步</Button>
            </div>
          </div>
        )}

        {/* Step 3: 地区偏好 */}
        {step === 3 && (
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">是否接受外省院校</label>
              <div className="flex gap-3">
                {[{ label: '接受', value: true }, { label: '仅本省', value: false }].map(opt => (
                  <button
                    key={String(opt.value)}
                    onClick={() => setAcceptsOutOfProvince(opt.value)}
                    className={`flex-1 py-2.5 rounded-btn text-sm border transition-colors ${
                      acceptsOutOfProvince === opt.value
                        ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">
                倾向城市 <span className="text-[#94A3B8] font-normal">（最多选 5 个）</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {CITIES.map(c => (
                  <button
                    key={c}
                    onClick={() => preferredCities.length < 5 || preferredCities.includes(c)
                      ? toggleItem(preferredCities, c, setPreferredCities)
                      : undefined}
                    className={`px-3 py-1.5 rounded-tag text-sm border transition-colors ${
                      preferredCities.includes(c)
                        ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">
                排除城市 <span className="text-[#94A3B8] font-normal">（不想去的城市）</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {CITIES.map(c => (
                  <button
                    key={c}
                    onClick={() => toggleItem(excludedCities, c, setExcludedCities)}
                    className={`px-3 py-1.5 rounded-tag text-sm border transition-colors ${
                      excludedCities.includes(c)
                        ? 'border-[#DC2626] bg-[#FEF2F2] text-[#DC2626]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>

            <div className="wj-actions flex gap-3 pt-2">
              <Button variant="outline" className="flex-1" onClick={goBack}>上一步</Button>
              <Button className="flex-1" onClick={goNext}>下一步</Button>
            </div>
          </div>
        )}

        {/* Step 4: 专业意向 */}
        {step === 4 && (
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">感兴趣的专业方向</label>
              <div className="flex flex-wrap gap-2">
                {MAJOR_GROUPS.map(m => (
                  <button
                    key={m}
                    onClick={() => toggleItem(interestedMajors, m, setInterestedMajors)}
                    className={`px-3 py-1.5 rounded-tag text-sm border transition-colors ${
                      interestedMajors.includes(m)
                        ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">
                排除专业方向 <span className="text-[#94A3B8] font-normal">（不考虑的方向）</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {MAJOR_GROUPS.map(m => (
                  <button
                    key={m}
                    onClick={() => toggleItem(excludedMajors, m, setExcludedMajors)}
                    className={`px-3 py-1.5 rounded-tag text-sm border transition-colors ${
                      excludedMajors.includes(m)
                        ? 'border-[#DC2626] bg-[#FEF2F2] text-[#DC2626]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            <div className="wj-actions flex gap-3 pt-2">
              <Button variant="outline" className="flex-1" onClick={goBack}>上一步</Button>
              <Button className="flex-1" onClick={goNext}>下一步</Button>
            </div>
          </div>
        )}

        {/* Step 5: 风险与预算 */}
        {step === 5 && (
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">志愿策略偏好</label>
              <div className="space-y-2">
                {[
                  { value: 'conservative' as const, label: '保守型', desc: '以保底为主，优先确保录取' },
                  { value: 'balanced' as const, label: '均衡型（推荐）', desc: '冲稳保均衡配置，综合最优' },
                  { value: 'aggressive' as const, label: '进取型', desc: '优先冲高，接受一定落榜风险' },
                ].map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => setRiskStyle(opt.value)}
                    className={`w-full text-left px-4 py-3 rounded-btn border transition-colors ${
                      riskStyle === opt.value
                        ? 'border-[#1E40AF] bg-[#EFF6FF]'
                        : 'border-[#E2E8F0] bg-white'
                    }`}
                  >
                    <p className={`text-sm font-medium ${riskStyle === opt.value ? 'text-[#1E40AF]' : 'text-[#0F172A]'}`}>
                      {opt.label}
                    </p>
                    <p className="text-xs text-[#64748B] mt-0.5">{opt.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[#0F172A] mb-2">家庭年均学费预算</label>
              <div className="flex flex-wrap gap-2">
                {['5000元以下', '5000-1万', '1-2万/年', '2-3万/年', '3万以上'].map(b => (
                  <button
                    key={b}
                    onClick={() => setBudgetRange(b)}
                    className={`px-3 py-1.5 rounded-tag text-sm border transition-colors ${
                      budgetRange === b
                        ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
                        : 'border-[#E2E8F0] text-[#64748B]'
                    }`}
                  >
                    {b}
                  </button>
                ))}
              </div>
            </div>

            <div className="wj-actions flex gap-3 pt-2">
              <Button variant="outline" className="flex-1" onClick={goBack}>上一步</Button>
              <Button className="flex-1" onClick={goNext}>下一步</Button>
            </div>
          </div>
        )}

        {/* Step 6: 确认提交 */}
        {step === 6 && (
          <div className="space-y-4">
            <div className="bg-white rounded-card border border-[#E2E8F0] divide-y divide-[#E2E8F0]">
              {[
                { label: '省份', value: formData.province },
                { label: '批次', value: formData.batch },
                { label: '分数', value: formData.score ? `${formData.score} 分` : '—' },
                { label: '位次', value: formData.rank ? `第 ${formData.rank} 名` : '未填写' },
                { label: '选科', value: subjects.join('、') || '未选择' },
                { label: '性别', value: gender || '未填写' },
                { label: '身体限制', value: hasPhysicalLimits ? '有' : '无' },
                { label: '倾向城市', value: preferredCities.join('、') || '不限' },
                { label: '专业意向', value: interestedMajors.join('、') || '不限' },
                { label: '志愿策略', value: { conservative: '保守型', balanced: '均衡型', aggressive: '进取型' }[riskStyle!] },
                { label: '预算范围', value: budgetRange },
              ].map(row => (
                <div key={row.label} className="flex items-start px-4 py-3">
                  <span className="text-sm text-[#64748B] w-20 flex-shrink-0">{row.label}</span>
                  <span className="text-sm text-[#0F172A] flex-1">{row.value}</span>
                </div>
              ))}
            </div>

            <p className="text-xs text-[#64748B]">
              确认信息无误后，点击「开始生成」，AI 将分析约 10 万条录取数据，为你生成专属志愿方案（约 15 分钟）
            </p>

            <div className="wj-actions flex gap-3 pt-2">
              <Button variant="outline" className="flex-1" onClick={goBack}>修改</Button>
              <Button className="flex-1" onClick={handleFinalSubmit} disabled={loading}>
                {loading ? '提交中...' : '开始生成'}
              </Button>
            </div>
          </div>
        )}
        </section>
      </main>
    </div>
  )
}
