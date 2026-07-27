'use client'

import { useState } from 'react'
import { Bot, ChevronDown, ChevronRight } from 'lucide-react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage, ChatCitation } from '@/types'
import CitationInline from './CitationInline'

interface Props {
  message: ChatMessage
}

const CITATION_PATTERN = /\[来源:([^\]]+)\]/g

/**
 * Turns `[来源:id]` markers into markdown links so they survive markdown parsing as inline nodes.
 * Uses a `#`-prefixed pseudo-href because react-markdown's default urlTransform strips unknown
 * URI schemes (e.g. `citation:`) as an XSS precaution, but passes through fragment links untouched.
 */
function preprocessCitations(content: string) {
  return content.replace(CITATION_PATTERN, (_match, sourceId) => `[来源:${sourceId}](#citation:${encodeURIComponent(sourceId)})`)
}

function buildMarkdownComponents(citations: ChatCitation[]): Components {
  return {
    a: ({ href, children }) => {
      if (href?.startsWith('#citation:')) {
        const sourceId = decodeURIComponent(href.slice('#citation:'.length))
        const citation = citations.find((c) => c.source_id === sourceId)
        return <CitationInline sourceId={sourceId} text={citation?.text ?? `来源 ${sourceId}`} />
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="text-brand-primary underline">
          {children}
        </a>
      )
    },
    p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    ul: ({ children }) => <ul className="mb-2 last:mb-0 list-disc pl-5 space-y-0.5">{children}</ul>,
    ol: ({ children }) => <ol className="mb-2 last:mb-0 list-decimal pl-5 space-y-0.5">{children}</ol>,
    li: ({ children }) => <li>{children}</li>,
    h1: ({ children }) => <h1 className="mb-2 mt-1 text-base font-semibold">{children}</h1>,
    h2: ({ children }) => <h2 className="mb-2 mt-1 text-body font-semibold">{children}</h2>,
    h3: ({ children }) => <h3 className="mb-1.5 mt-1 text-sm font-semibold">{children}</h3>,
    code: ({ children }) => (
      <code className="rounded bg-neutral-border/60 px-1 py-0.5 font-mono text-caption">{children}</code>
    ),
    pre: ({ children }) => (
      <pre className="mb-2 last:mb-0 overflow-x-auto rounded-btn bg-[#0F172A] p-3 text-caption text-white">
        {children}
      </pre>
    ),
    table: ({ children }) => (
      <div className="mb-2 last:mb-0 overflow-x-auto">
        <table className="min-w-full border-collapse text-caption">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-neutral-border/40">{children}</thead>,
    th: ({ children }) => (
      <th className="border border-neutral-border px-2 py-1 text-left font-semibold">{children}</th>
    ),
    td: ({ children }) => <td className="border border-neutral-border px-2 py-1">{children}</td>,
  }
}

/**
 * 可展开的"AI 推理过程"面板——展示 kimi-k2.6 的 reasoning_content（已经过
 * _ThinkingBuffer 按句子片段做过合规过滤，不是完全原始的模型输出）。
 *
 * `defaultExpanded` 由调用方按阶段传入，不是写死的：正在思考、还没出现正式回复
 * 内容时默认展开（此时这是屏幕上唯一有信息量的东西，应该主动露出而不是让用户
 * 去点）；正式内容一开始生成、或者这条消息已经生成完毕，就默认收起，避免这段
 * 技术性文字常驻挤占版面。用户如果手动点过一次，之后就按用户的选择来，不再被
 * `defaultExpanded` 的变化覆盖。
 */
export function ThinkingDisclosure({
  thinking,
  label = '查看AI推理过程',
  defaultExpanded = false,
  pulsing = false,
}: {
  thinking: string
  label?: string
  defaultExpanded?: boolean
  pulsing?: boolean
}) {
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null)
  const expanded = manualExpanded ?? defaultExpanded
  return (
    <div className="mt-1.5">
      <button
        onClick={() => setManualExpanded(!expanded)}
        className="flex items-center gap-1 text-caption text-[#94A3B8] hover:text-[#64748B] transition-colors"
      >
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span className={pulsing ? 'animate-pulse' : undefined}>{label}</span>
      </button>
      {expanded && (
        <div
          key={thinking.length}
          className="mt-1 px-3 py-2 rounded-btn bg-[#F8FAFC] border border-[#E2E8F0]
          text-caption text-[#64748B] whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto
          wj-stream-fade-in"
        >
          {thinking}
        </div>
      )}
    </div>
  )
}

export default function ChatMessageBubble({ message }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] px-3.5 py-2.5 rounded-bubble rounded-tr-sm
          bg-[#EFF6FF] text-[#0F172A] text-sm leading-relaxed break-words">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-2 items-start">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-[#1E40AF] to-[#2563EB]
        flex items-center justify-center mt-0.5">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="max-w-[85%] pt-1 text-sm leading-relaxed text-[#0F172A] break-words">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents(message.citations)}>
          {preprocessCitations(message.content)}
        </ReactMarkdown>
        {message.thinking && <ThinkingDisclosure thinking={message.thinking} />}
      </div>
    </div>
  )
}

/** Typing indicator shown while AI is streaming */
export function ChatTypingIndicator() {
  return (
    <div className="flex gap-2 items-start">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-[#1E40AF] to-[#2563EB]
        flex items-center justify-center">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="pt-1.5">
        <div className="flex gap-1 items-center h-4">
          <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:0ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:150ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  )
}

/**
 * Streaming bubble shows partial content while tokens arrive. `thinking` is
 * kimi-k2.6's hidden reasoning_content, buffered+compliance-filtered on the
 * backend (see intake_agent.py::_ThinkingBuffer) — while real content hasn't
 * started yet, this is the only signal that anything is happening at all, so
 * it's shown expanded by default (growing live) instead of a bare "AI 正在
 * 思考..." placeholder; once content starts, it auto-collapses to make room
 * for the real answer without losing the ability to expand it again (see
 * docs/疑问杂项.md「/api/v1/intake/chat 响应慢的原因与优化方向」)。
 */
export function ChatStreamingBubble({ content, thinking }: { content: string; thinking?: string }) {
  return (
    <div className="flex gap-2 items-start">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-[#1E40AF] to-[#2563EB]
        flex items-center justify-center mt-0.5">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="max-w-[85%] pt-1 text-sm leading-relaxed text-[#0F172A] break-words">
        {thinking && (
          <ThinkingDisclosure
            thinking={thinking}
            label={content ? '查看AI推理过程' : 'AI 正在思考…'}
            defaultExpanded={!content}
            pulsing={!content}
          />
        )}
        {content ? (
          // key 按内容长度变化——配合 IntakeChat.tsx 里的 rAF 批量刷新，每批新增
          // 文本到达时重新触发一次淡入动画，而不是让整段文字生硬地"跳"出来。
          <div key={content.length} className="wj-stream-fade-in">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents([])}>
              {preprocessCitations(content)}
            </ReactMarkdown>
          </div>
        ) : !thinking ? (
          <div className="flex gap-1 items-center h-4">
            <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:300ms]" />
          </div>
        ) : null}
        <span className="inline-block w-0.5 h-4 bg-[#1E40AF] animate-pulse ml-0.5 align-text-bottom" />
      </div>
    </div>
  )
}
