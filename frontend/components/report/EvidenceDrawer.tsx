'use client'

import { useEffect, useState } from 'react'
import { X, FileText, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react'

interface ChunkItem {
  id: string
  content: string
  metadata: Record<string, unknown>
}

interface SourceDetail {
  id: string
  type: string
  title: string
  sourceUrl?: string
  year?: number
  authorityLevel?: string
  status: string
  chunks: ChunkItem[]
}

interface EvidenceDrawerProps {
  open: boolean
  onClose: () => void
  evidenceIds: string[]
  schoolName: string
}

const TYPE_LABELS: Record<string, string> = {
  charter: '招生章程',
  major_intro: '专业介绍',
  employment_report: '就业报告',
  policy: '政策文件',
  admission_plan: '招生计划',
  admission_score: '录取分数',
}

const AUTH_COLORS: Record<string, string> = {
  official: 'bg-[rgba(143,224,183,0.12)] text-[#8FE0B7]',
  'semi-official': 'bg-[rgba(169,180,245,0.12)] text-[#A9B4F5]',
  'third-party': 'bg-white/10 text-[#9CA3C4]',
  internal: 'bg-[rgba(239,196,138,0.12)] text-[#EFC48A]',
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function fetchSource(id: string): Promise<SourceDetail> {
  const res = await fetch(`${BASE_URL}/api/v1/sources/${id}`, { credentials: 'include' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const d = await res.json()
  return {
    id: d.id,
    type: d.type,
    title: d.title,
    sourceUrl: d.source_url,
    year: d.year,
    authorityLevel: d.authority_level,
    status: d.status,
    chunks: d.chunks,
  }
}

function SourceCard({ source }: { source: SourceDetail }) {
  const [expanded, setExpanded] = useState(false)
  const authColor = AUTH_COLORS[source.authorityLevel ?? ''] ?? 'bg-gray-100 text-gray-600'

  return (
    <div className="border border-white/10 rounded-xl overflow-hidden">
      <div className="p-4">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 bg-[rgba(167,139,250,0.14)] rounded-lg flex items-center justify-center shrink-0">
            <FileText className="w-4 h-4 text-[#A78BFA]" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-[#F1F5F9] leading-snug">{source.title}</p>
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              <span className="text-xs text-[#6B7280]">
                {TYPE_LABELS[source.type] ?? source.type}
              </span>
              {source.year && (
                <span className="text-xs text-[#6B7280]">{source.year} 年</span>
              )}
              {source.authorityLevel && (
                <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${authColor}`}>
                  {source.authorityLevel === 'official'
                    ? '官方'
                    : source.authorityLevel === 'semi-official'
                    ? '半官方'
                    : source.authorityLevel === 'third-party'
                    ? '第三方'
                    : source.authorityLevel}
                </span>
              )}
            </div>
          </div>
          {source.sourceUrl && (
            <a
              href={source.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 text-[#A78BFA] hover:opacity-80"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          )}
        </div>

        {source.chunks.length > 0 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-3 flex items-center gap-1 text-xs text-[#A78BFA] hover:opacity-80"
          >
            {expanded ? (
              <><ChevronUp className="w-3.5 h-3.5" />收起摘要</>
            ) : (
              <><ChevronDown className="w-3.5 h-3.5" />查看摘要（{source.chunks.length} 段）</>
            )}
          </button>
        )}
      </div>

      {expanded && source.chunks.length > 0 && (
        <div className="border-t border-white/10 divide-y divide-white/10">
          {source.chunks.map((chunk) => (
            <div key={chunk.id} className="px-4 py-3 bg-white/[0.02]">
              <p className="text-xs text-[#9CA3C4] leading-relaxed line-clamp-4">
                {chunk.content}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function EvidenceDrawer({
  open,
  onClose,
  evidenceIds,
  schoolName,
}: EvidenceDrawerProps) {
  const [sources, setSources] = useState<SourceDetail[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || evidenceIds.length === 0) return
    setLoading(true)
    setError('')
    Promise.all(evidenceIds.map(fetchSource))
      .then(setSources)
      .catch(() => setError('加载证据来源失败'))
      .finally(() => setLoading(false))
  }, [open, evidenceIds.join(',')])

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Bottom sheet */}
      <div className="fixed bottom-0 left-0 right-0 z-50 bg-[rgba(10,8,38,0.96)] backdrop-blur border-t border-white/10 rounded-t-2xl shadow-2xl max-h-[75vh] flex flex-col">
        {/* Handle + header */}
        <div className="flex-shrink-0 px-4 pt-3 pb-4 border-b border-white/10">
          <div className="w-10 h-1 bg-white/20 rounded-full mx-auto mb-3" />
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-bold text-[#F1F5F9]">数据来源</p>
              <p className="text-xs text-[#6B7280] mt-0.5">{schoolName}</p>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/15 transition-colors"
            >
              <X className="w-4 h-4 text-[#9CA3C4]" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {loading && (
            <div className="py-8 text-center text-sm text-[#6B7280]">加载中...</div>
          )}
          {error && (
            <div className="py-6 text-center text-sm text-[#F2A9A9]">{error}</div>
          )}
          {!loading && !error && sources.length === 0 && evidenceIds.length === 0 && (
            <div className="py-8 text-center text-sm text-[#6B7280]">该推荐暂无关联证据来源</div>
          )}
          {sources.map((s) => (
            <SourceCard key={s.id} source={s} />
          ))}
        </div>
      </div>
    </>
  )
}
