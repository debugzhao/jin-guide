'use client'

import { useState } from 'react'
import { api, VolunteerCheckResult } from '@/lib/api'

type Tier = 'high_rush' | 'rush' | 'target' | 'safe'

interface VolunteerRow {
  id: number
  universityName: string
  majorName: string
  tier: Tier
}

const TIER_LABELS: Record<Tier, string> = {
  high_rush: '高冲',
  rush: '冲刺',
  target: '稳妥',
  safe: '保底',
}

const TIER_COLORS: Record<Tier, string> = {
  high_rush: 'bg-red-100 text-red-700 border-red-200',
  rush: 'bg-orange-100 text-orange-700 border-orange-200',
  target: 'bg-blue-100 text-blue-700 border-blue-200',
  safe: 'bg-green-100 text-green-700 border-green-200',
}

const SEV_CONFIG = {
  high: { color: 'border-red-400 bg-red-50', badge: 'bg-red-500 text-white', label: '高风险' },
  medium: { color: 'border-yellow-400 bg-yellow-50', badge: 'bg-yellow-500 text-white', label: '中风险' },
  low: { color: 'border-blue-300 bg-blue-50', badge: 'bg-blue-400 text-white', label: '提示' },
}

const RISK_CONFIG = {
  low: { label: '风险较低', color: 'text-green-600', bg: 'bg-green-50 border-green-200' },
  medium: { label: '存在风险', color: 'text-yellow-600', bg: 'bg-yellow-50 border-yellow-200' },
  high: { label: '高风险', color: 'text-red-600', bg: 'bg-red-50 border-red-200' },
}

let _id = 0

function newRow(overrides?: Partial<VolunteerRow>): VolunteerRow {
  return { id: ++_id, universityName: '', majorName: '', tier: 'target', ...overrides }
}

export default function VolunteerCheckPage() {
  const [rows, setRows] = useState<VolunteerRow[]>([
    newRow({ universityName: '', majorName: '', tier: 'rush' }),
    newRow({ universityName: '', majorName: '', tier: 'target' }),
    newRow({ universityName: '', majorName: '', tier: 'safe' }),
  ])
  const [rejectedMajors, setRejectedMajors] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<VolunteerCheckResult | null>(null)
  const [error, setError] = useState('')

  const updateRow = (id: number, field: keyof VolunteerRow, value: string) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)))
  }

  const removeRow = (id: number) => {
    setRows((prev) => prev.filter((r) => r.id !== id))
  }

  const handleSubmit = async () => {
    const valid = rows.filter((r) => r.universityName.trim() && r.majorName.trim())
    if (valid.length === 0) {
      setError('请至少填写一条志愿信息')
      return
    }
    setError('')
    setLoading(true)
    try {
      const res = await api.checkVolunteer({
        volunteers: valid.map((r) => ({
          universityName: r.universityName.trim(),
          majorName: r.majorName.trim(),
          tier: r.tier,
        })),
        rejectedMajors: rejectedMajors
          .split(/[,，\s]+/)
          .map((s) => s.trim())
          .filter(Boolean),
      })
      setResult(res)
    } catch {
      setError('体检接口请求失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const tierDist = result?.tierDistribution ?? {}

  return (
    <div className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900">志愿表体检</h1>
          <p className="text-sm text-gray-500 mt-1">输入已填写的志愿院校与专业，快速识别潜在风险点</p>
        </div>

        {/* Input table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
          <div className="grid grid-cols-12 gap-0 bg-gray-50 border-b border-gray-200 px-4 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
            <div className="col-span-4">院校名称</div>
            <div className="col-span-4">专业名称</div>
            <div className="col-span-3">档位</div>
            <div className="col-span-1" />
          </div>

          <div className="divide-y divide-gray-100">
            {rows.map((row, idx) => (
              <div key={row.id} className="grid grid-cols-12 gap-2 px-4 py-2 items-center">
                <div className="col-span-4">
                  <input
                    className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder={`院校 ${idx + 1}`}
                    value={row.universityName}
                    onChange={(e) => updateRow(row.id, 'universityName', e.target.value)}
                  />
                </div>
                <div className="col-span-4">
                  <input
                    className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="专业名称"
                    value={row.majorName}
                    onChange={(e) => updateRow(row.id, 'majorName', e.target.value)}
                  />
                </div>
                <div className="col-span-3">
                  <select
                    className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                    value={row.tier}
                    onChange={(e) => updateRow(row.id, 'tier', e.target.value)}
                  >
                    {(Object.keys(TIER_LABELS) as Tier[]).map((t) => (
                      <option key={t} value={t}>{TIER_LABELS[t]}</option>
                    ))}
                  </select>
                </div>
                <div className="col-span-1 flex justify-center">
                  <button
                    onClick={() => removeRow(row.id)}
                    className="text-gray-300 hover:text-red-400 transition-colors text-lg leading-none"
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="px-4 py-3 border-t border-gray-100">
            <button
              onClick={() => setRows((p) => [...p, newRow()])}
              className="text-sm text-blue-600 hover:text-blue-700 font-medium"
            >
              + 添加志愿
            </button>
          </div>
        </div>

        {/* Rejected majors */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            不服从调剂专业
            <span className="ml-1 text-xs text-gray-400">（逗号分隔，如：临床医学, 法学）</span>
          </label>
          <input
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="例如：临床医学, 法学"
            value={rejectedMajors}
            onChange={(e) => setRejectedMajors(e.target.value)}
          />
        </div>

        {error && (
          <p className="text-sm text-red-500 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
            {error}
          </p>
        )}

        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold text-base transition-colors"
        >
          {loading ? '体检中...' : '开始体检'}
        </button>

        {/* Results */}
        {result && (
          <div className="space-y-4">
            {/* Risk summary bar */}
            <div className={`rounded-xl border p-5 flex items-center justify-between ${RISK_CONFIG[result.overallRisk].bg}`}>
              <div>
                <p className={`text-xl font-bold ${RISK_CONFIG[result.overallRisk].color}`}>
                  {RISK_CONFIG[result.overallRisk].label}
                </p>
                <p className="text-sm text-gray-500 mt-0.5">
                  共 {result.total} 条志愿 · 保底 {result.safeCount} 所
                </p>
              </div>
              <div className="text-right">
                <p className="text-3xl font-bold text-gray-800">{result.riskScore}</p>
                <p className="text-xs text-gray-400">风险评分</p>
              </div>
            </div>

            {/* Tier distribution */}
            <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
              <p className="text-sm font-medium text-gray-600 mb-3">档位分布</p>
              <div className="grid grid-cols-4 gap-3">
                {(Object.keys(TIER_LABELS) as Tier[]).map((t) => (
                  <div key={t} className={`rounded-lg border px-3 py-2 text-center ${TIER_COLORS[t]}`}>
                    <p className="text-xl font-bold">{tierDist[t] ?? 0}</p>
                    <p className="text-xs mt-0.5">{TIER_LABELS[t]}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Risk items */}
            {result.riskItems.length > 0 ? (
              <div className="space-y-3">
                <p className="text-sm font-medium text-gray-600">
                  发现 {result.riskItems.length} 项风险
                </p>
                {result.riskItems.map((item, i) => {
                  const cfg = SEV_CONFIG[item.severity]
                  return (
                    <div key={i} className={`rounded-xl border-l-4 p-4 ${cfg.color}`}>
                      <div className="flex items-start gap-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${cfg.badge}`}>
                          {cfg.label}
                        </span>
                        <p className="text-sm text-gray-700 leading-relaxed">{item.message}</p>
                      </div>
                      {item.targets.length > 0 && (
                        <ul className="mt-2 ml-16 space-y-0.5">
                          {item.targets.map((t, j) => (
                            <li key={j} className="text-xs text-gray-500">· {t}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center text-sm text-green-700">
                未发现明显风险，志愿结构良好
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
