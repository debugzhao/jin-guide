'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import Button from '@/components/ui/Button'
import ClarificationBubble from './ClarificationBubble'
import { api, type FieldCheckIssue } from '@/lib/api'
import {
  REQUIRED_FIELD_KEYS,
  PROFILE_FIELD_SCHEMA,
  OTHER_SUBJECTS,
} from '@/lib/profileFieldSchema'

interface ProfileCaptureCardProps {
  profileId?: string
  onSubmit: (values: Record<string, unknown>) => void
  submitting?: boolean
}

const inputClass =
  'wj-glass-card w-full rounded-btn px-3 py-2 text-sm text-[#0F172A] placeholder:text-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#1E40AF]/40'

const chipClass = (active: boolean) =>
  cn(
    'px-2.5 py-1 rounded-tag text-xs border transition-colors',
    active
      ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
      : 'border-[#E2E8F0] text-[#64748B] hover:border-[#CBD5E1]'
  )

const pillClass = (active: boolean) =>
  cn(
    'flex-1 px-3 py-2 rounded-btn text-sm border text-center transition-colors',
    active
      ? 'border-[#1E40AF] bg-[#EFF6FF] text-[#1E40AF]'
      : 'border-[#E2E8F0] text-[#64748B] hover:border-[#CBD5E1]'
  )

/**
 * 「基础建档信息」卡片 —— 所有必填字段一起展示在同一张两列网格卡片里
 * （docs/wenjin-agent-prototype.html 第 1048-1095 行是当前交互事实源），
 * 不是逐条对话气泡。字段跳过/依赖仍是纯本地判断，矛盾检测（位次/选科）
 * 在点击确认按钮时统一调用一次 `/profile/field-check`。
 */
export default function ProfileCaptureCard({ profileId, onSubmit, submitting }: ProfileCaptureCardProps) {
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [subjectPrimary, setSubjectPrimary] = useState<'物理' | '历史' | ''>('')
  const [subjectOthers, setSubjectOthers] = useState<string[]>([])
  const [hasMedicalLimit, setHasMedicalLimit] = useState<boolean | null>(null)
  const [medicalDetails, setMedicalDetails] = useState<string[]>([])
  const [checking, setChecking] = useState(false)
  const [clarification, setClarification] = useState<{ field: string; issue: FieldCheckIssue } | null>(null)

  const set = (key: string, value: unknown) => setValues((prev) => ({ ...prev, [key]: value }))

  const subjects = subjectPrimary ? [subjectPrimary, ...subjectOthers] : []
  const requiredFilled =
    !!values.province &&
    !!values.batch &&
    typeof values.score === 'number' &&
    subjects.length > 0 &&
    !!values.gender &&
    hasMedicalLimit !== null &&
    (hasMedicalLimit === false || medicalDetails.length > 0)

  const handleSubmit = async () => {
    if (!requiredFilled || checking) return
    setChecking(true)
    setClarification(null)

    const known = {
      province: values.province,
      batch: values.batch,
    }

    try {
      if (values.rank) {
        const rankCheck = await api.checkProfileField({
          profileId, field: 'rank', value: values.rank, knownFields: known,
        })
        if (rankCheck.status === 'needs_clarification' && rankCheck.issue) {
          setClarification({ field: 'rank', issue: rankCheck.issue })
          return
        }
      }
      const subjectCheck = await api.checkProfileField({
        profileId, field: 'subjects', value: subjects, knownFields: known,
      })
      if (subjectCheck.status === 'needs_clarification' && subjectCheck.issue) {
        setClarification({ field: 'subjects', issue: subjectCheck.issue })
        return
      }
    } catch {
      // field-check 服务不可用时不阻塞建档，按无矛盾处理
    } finally {
      setChecking(false)
    }

    onSubmit({
      ...values,
      subjects,
      has_physical_limits: hasMedicalLimit,
      medical_restrictions: hasMedicalLimit ? medicalDetails : [],
    })
  }

  const handleClarificationAction = (action: string) => {
    if (action === 'continue_anyway') {
      setClarification(null)
      onSubmit({
        ...values,
        subjects,
        has_physical_limits: hasMedicalLimit,
        medical_restrictions: hasMedicalLimit ? medicalDetails : [],
      })
    } else {
      // 调整类 action：清空追问，把控制权交回表单本身，用户可以直接改字段重新提交
      setClarification(null)
    }
  }

  return (
    <div className="wj-glass-card rounded-bubble rounded-tl-sm px-4 py-3 max-w-[96%] space-y-3">
      <div className="text-xs text-[#64748B]">问津助手</div>
      <p className="text-sm text-[#0F172A]">
        先填写生成志愿报告必须依赖的基础信息。这里不完整时，我只能做快速答疑，不能渲染右侧报告。
      </p>

      <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-btn p-3.5 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <strong className="text-sm text-[#0F172A]">基础建档信息</strong>
          <span className="text-xs px-2 py-0.5 rounded-tag bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]">
            必填
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="flex flex-col gap-1.5 text-xs text-[#64748B]">
            {PROFILE_FIELD_SCHEMA.province.label}
            <select
              className={inputClass}
              value={(values.province as string) ?? ''}
              onChange={(e) => set('province', e.target.value)}
            >
              <option value="" disabled>请选择省份</option>
              {PROFILE_FIELD_SCHEMA.province.options?.map((o) => (
                <option key={o.value} value={o.value} className="bg-white text-[#0F172A]">{o.label}</option>
              ))}
            </select>
          </label>

          <div className="flex flex-col gap-1.5 text-xs text-[#64748B]">
            {PROFILE_FIELD_SCHEMA.batch.label}
            <div className="flex gap-2">
              {PROFILE_FIELD_SCHEMA.batch.options?.map((o) => (
                <button key={o.value} type="button" className={pillClass(values.batch === o.value)} onClick={() => set('batch', o.value)}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          <label className="flex flex-col gap-1.5 text-xs text-[#64748B]">
            {PROFILE_FIELD_SCHEMA.score.label}
            <input
              type="number"
              className={inputClass}
              placeholder={PROFILE_FIELD_SCHEMA.score.placeholder}
              value={(values.score as number) ?? ''}
              onChange={(e) => set('score', e.target.value === '' ? undefined : Number(e.target.value))}
            />
          </label>

          <label className="flex flex-col gap-1.5 text-xs text-[#64748B]">
            {PROFILE_FIELD_SCHEMA.rank.label}
            <input
              type="number"
              className={inputClass}
              placeholder={PROFILE_FIELD_SCHEMA.rank.placeholder}
              value={(values.rank as number) ?? ''}
              onChange={(e) => set('rank', e.target.value === '' ? undefined : Number(e.target.value))}
            />
          </label>

          <div className="md:col-span-2 flex flex-col gap-1.5 text-xs text-[#64748B]">
            {PROFILE_FIELD_SCHEMA.subjects.label}
            <div className="flex gap-2">
              {(['物理', '历史'] as const).map((s) => (
                <button key={s} type="button" className={pillClass(subjectPrimary === s)} onClick={() => setSubjectPrimary(s)}>
                  {s}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2 mt-1">
              {OTHER_SUBJECTS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={chipClass(subjectOthers.includes(s))}
                  onClick={() => setSubjectOthers((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5 text-xs text-[#64748B]">
            {PROFILE_FIELD_SCHEMA.gender.label}
            <div className="flex gap-2">
              {PROFILE_FIELD_SCHEMA.gender.options?.map((o) => (
                <button key={o.value} type="button" className={pillClass(values.gender === o.value)} onClick={() => set('gender', o.value)}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          <div className="md:col-span-2 flex flex-col gap-1.5 text-xs text-[#64748B]">
            {PROFILE_FIELD_SCHEMA.has_physical_limits.label}
            <p className="text-micro text-[#94A3B8]">{PROFILE_FIELD_SCHEMA.has_physical_limits.helpText}</p>
            <div className="flex gap-2">
              <button type="button" className={pillClass(hasMedicalLimit === false)} onClick={() => { setHasMedicalLimit(false); setMedicalDetails([]) }}>
                无限制
              </button>
              <button type="button" className={pillClass(hasMedicalLimit === true)} onClick={() => setHasMedicalLimit(true)}>
                有限制
              </button>
            </div>
            {hasMedicalLimit === true && (
              <div className="flex flex-wrap gap-2 mt-1">
                {PROFILE_FIELD_SCHEMA.has_physical_limits.options?.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    className={chipClass(medicalDetails.includes(o.value))}
                    onClick={() => setMedicalDetails((prev) => prev.includes(o.value) ? prev.filter((x) => x !== o.value) : [...prev, o.value])}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <p className="text-xs text-[#94A3B8]">分数和位次至少填一个；同时填写时，匹配会优先使用位次。</p>

        <Button className="w-full" onClick={handleSubmit} disabled={!requiredFilled || checking || submitting}>
          {checking ? '校验中...' : submitting ? '生成中...' : '确认基础信息并渲染报告'}
        </Button>
      </div>

      {clarification && (
        <ClarificationBubble issue={clarification.issue} onAction={handleClarificationAction} />
      )}
    </div>
  )
}
