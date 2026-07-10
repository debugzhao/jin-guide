'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { FieldSchemaEntry } from '@/lib/profileFieldSchema'
import { OTHER_SUBJECTS } from '@/lib/profileFieldSchema'
import Button from '@/components/ui/Button'

interface FieldControlProps {
  entry: FieldSchemaEntry
  onSubmit: (value: unknown) => void
}

const chipClass = (active: boolean) =>
  cn(
    'px-3 py-1.5 rounded-tag text-sm border transition-colors',
    active
      ? 'border-[#A78BFA] bg-[rgba(167,139,250,0.14)] text-[#A78BFA]'
      : 'border-white/10 text-[#9CA3C4] hover:border-white/20'
  )

const cardClass = (active: boolean) =>
  cn(
    'w-full text-left px-4 py-3 rounded-card border transition-colors',
    active ? 'border-[#A78BFA] bg-[rgba(167,139,250,0.10)]' : 'border-white/10 wj-glass-card'
  )

/** 单个建档字段的结构化控件；不同 controlType 渲染不同交互，选择完成后调用 onSubmit。 */
export default function FieldControl({ entry, onSubmit }: FieldControlProps) {
  switch (entry.controlType) {
    case 'select':
      return <SelectControl entry={entry} onSubmit={onSubmit} />
    case 'radio-group':
      return <RadioGroupControl entry={entry} onSubmit={onSubmit} />
    case 'number-input':
      return <NumberInputControl entry={entry} onSubmit={onSubmit} />
    case 'subject-picker':
      return <SubjectPickerControl onSubmit={onSubmit} />
    case 'boolean-with-detail':
      return <BooleanWithDetailControl entry={entry} onSubmit={onSubmit} />
    case 'plan-cards':
      return <PlanCardsControl entry={entry} onSubmit={onSubmit} />
    case 'chip-multiselect':
      return <ChipMultiselectControl entry={entry} onSubmit={onSubmit} />
    default:
      return null
  }
}

function SelectControl({ entry, onSubmit }: FieldControlProps) {
  return (
    <select
      defaultValue=""
      onChange={(e) => e.target.value && onSubmit(e.target.value)}
      className="wj-glass-card w-full rounded-btn px-3 py-2.5 text-sm text-[#F1F5F9] focus:outline-none focus:ring-2 focus:ring-[#A78BFA]/40"
    >
      <option value="" disabled>{entry.placeholder ?? '请选择'}</option>
      {entry.options?.map((o) => (
        <option key={o.value} value={o.value} className="bg-[#0A0826] text-[#F1F5F9]">
          {o.label}
        </option>
      ))}
    </select>
  )
}

function RadioGroupControl({ entry, onSubmit }: FieldControlProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {entry.options?.map((o) => (
        <button
          key={o.value}
          onClick={() => onSubmit(o.value)}
          className="px-4 py-2 rounded-btn text-sm border border-white/10 wj-glass-card text-[#F1F5F9] hover:border-[#A78BFA]/50 transition-colors"
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function NumberInputControl({ entry, onSubmit }: FieldControlProps) {
  const [value, setValue] = useState('')
  const submit = () => {
    const n = Number(value)
    if (value.trim() !== '' && !Number.isNaN(n)) onSubmit(n)
  }
  return (
    <div className="flex gap-2">
      <input
        type="number"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        placeholder={entry.placeholder}
        className="wj-glass-card flex-1 rounded-btn px-3 py-2.5 text-sm text-[#F1F5F9] placeholder:text-[#6B7280] focus:outline-none focus:ring-2 focus:ring-[#A78BFA]/40"
      />
      <Button size="md" onClick={submit}>确认</Button>
      {!entry.required && (
        <Button size="md" variant="ghost" onClick={() => onSubmit(undefined)}>跳过</Button>
      )}
    </div>
  )
}

function SubjectPickerControl({ onSubmit }: Pick<FieldControlProps, 'onSubmit'>) {
  const [primary, setPrimary] = useState<'物理' | '历史' | ''>('')
  const [others, setOthers] = useState<string[]>([])

  const toggleOther = (s: string) =>
    setOthers((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]))

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs text-[#9CA3C4] mb-1.5">物理 / 历史（单选）</p>
        <div className="flex gap-2">
          {(['物理', '历史'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setPrimary(s)}
              className={cardClass(primary === s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      <div>
        <p className="text-xs text-[#9CA3C4] mb-1.5">其余选考科目（多选）</p>
        <div className="flex flex-wrap gap-2">
          {OTHER_SUBJECTS.map((s) => (
            <button key={s} onClick={() => toggleOther(s)} className={chipClass(others.includes(s))}>
              {s}
            </button>
          ))}
        </div>
      </div>
      <Button size="md" disabled={!primary} onClick={() => onSubmit([primary, ...others])}>
        确认选科
      </Button>
    </div>
  )
}

function BooleanWithDetailControl({ entry, onSubmit }: FieldControlProps) {
  const [hasLimit, setHasLimit] = useState<boolean | null>(null)
  const [details, setDetails] = useState<string[]>([])

  const toggleDetail = (d: string) =>
    setDetails((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]))

  if (hasLimit === null) {
    return (
      <div className="flex gap-3">
        <button className={cardClass(false)} onClick={() => onSubmit([])}>无限制</button>
        <button className={cardClass(false)} onClick={() => setHasLimit(true)}>有限制</button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {entry.options?.map((o) => (
          <button key={o.value} onClick={() => toggleDetail(o.value)} className={chipClass(details.includes(o.value))}>
            {o.label}
          </button>
        ))}
      </div>
      <Button size="md" disabled={details.length === 0} onClick={() => onSubmit(details)}>
        确认
      </Button>
    </div>
  )
}

function PlanCardsControl({ entry, onSubmit }: FieldControlProps) {
  return (
    <div className="space-y-2">
      {entry.options?.map((o) => (
        <button key={o.value} onClick={() => onSubmit(o.value)} className={cardClass(false)}>
          <span className="text-sm text-[#F1F5F9]">{o.label}</span>
        </button>
      ))}
      <Button size="sm" variant="ghost" onClick={() => onSubmit(undefined)}>跳过，先用默认策略</Button>
    </div>
  )
}

function ChipMultiselectControl({ entry, onSubmit }: FieldControlProps) {
  const [selected, setSelected] = useState<string[]>([])
  const toggle = (v: string) =>
    setSelected((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {entry.options?.map((o) => (
          <button key={o.value} onClick={() => toggle(o.value)} className={chipClass(selected.includes(o.value))}>
            {o.label}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <Button size="sm" onClick={() => onSubmit(selected)} disabled={selected.length === 0}>
          确认（已选 {selected.length}）
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onSubmit([])}>不限，跳过</Button>
      </div>
    </div>
  )
}
