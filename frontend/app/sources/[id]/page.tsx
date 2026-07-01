'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, ExternalLink, FileText, AlertCircle } from 'lucide-react'

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

const TYPE_LABELS: Record<string, string> = {
  charter: '招生章程',
  major_intro: '专业介绍',
  employment_report: '就业质量报告',
  policy: '政策文件',
  admission_plan: '招生计划',
  admission_score: '录取分数线',
}

const STATUS_COLORS: Record<string, string> = {
  published: 'bg-green-100 text-green-700',
  verified: 'bg-blue-100 text-blue-700',
  parsed: 'bg-yellow-100 text-yellow-700',
  raw: 'bg-gray-100 text-gray-600',
}

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function SourceDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [source, setSource] = useState<SourceDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    fetch(`${BASE_URL}/api/v1/sources/${id}`, { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d) =>
        setSource({
          id: d.id,
          type: d.type,
          title: d.title,
          sourceUrl: d.source_url,
          year: d.year,
          authorityLevel: d.authority_level,
          status: d.status,
          chunks: d.chunks,
        })
      )
      .catch(() => setError('加载数据来源失败，请检查网络或稍后重试'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-400 text-sm">加载中...</p>
      </div>
    )
  }

  if (error || !source) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-3">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-gray-600 text-sm">{error || '来源不存在'}</p>
        <button
          onClick={() => router.back()}
          className="text-blue-600 text-sm underline underline-offset-2"
        >
          返回
        </button>
      </div>
    )
  }

  const statusColor = STATUS_COLORS[source.status] ?? 'bg-gray-100 text-gray-600'
  const statusLabel: Record<string, string> = {
    published: '已发布',
    verified: '已验证',
    parsed: '已解析',
    raw: '原始',
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 transition-colors"
          >
            <ArrowLeft className="w-4 h-4 text-gray-600" />
          </button>
          <p className="text-sm font-semibold text-gray-800 truncate">{source.title}</p>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
        {/* Metadata card */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center shrink-0">
              <FileText className="w-5 h-5 text-blue-600" />
            </div>
            <div className="flex-1">
              <h1 className="text-base font-bold text-gray-900 leading-snug">
                {source.title}
              </h1>
              <div className="flex flex-wrap items-center gap-2 mt-2">
                <span className="text-xs text-gray-500">
                  {TYPE_LABELS[source.type] ?? source.type}
                </span>
                {source.year && (
                  <span className="text-xs text-gray-400">· {source.year} 年</span>
                )}
                {source.authorityLevel && (
                  <span className="text-xs text-gray-400">
                    ·{' '}
                    {{
                      official: '官方来源',
                      'semi-official': '半官方',
                      'third-party': '第三方',
                      internal: '内部',
                    }[source.authorityLevel] ?? source.authorityLevel}
                  </span>
                )}
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusColor}`}>
                  {statusLabel[source.status] ?? source.status}
                </span>
              </div>
            </div>
          </div>

          {source.sourceUrl && (
            <a
              href={source.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-700"
            >
              <ExternalLink className="w-4 h-4" />
              查看原始来源
            </a>
          )}
        </div>

        {/* Chunks */}
        {source.chunks.length > 0 ? (
          <div className="space-y-3">
            <p className="text-sm font-medium text-gray-600">
              文档摘要（共 {source.chunks.length} 段）
            </p>
            {source.chunks.map((chunk, idx) => (
              <div
                key={chunk.id}
                className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-gray-400">第 {idx + 1} 段</span>
                  {chunk.metadata.chunk_index !== undefined && (
                    <span className="text-xs text-gray-300">
                      · chunk #{chunk.metadata.chunk_index as number}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">{chunk.content}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 p-6 text-center text-sm text-gray-400">
            该文档暂无内容摘要
          </div>
        )}
      </div>
    </div>
  )
}
