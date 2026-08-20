'use client'

import { memo, useDeferredValue, useState } from 'react'
import { Bot, ChevronDown, ChevronRight } from 'lucide-react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage, ChatCitation } from '@/types'
import CitationInline from './CitationInline'

interface Props {
  message: ChatMessage
  showReasoning?: boolean
}

const CITATION_PATTERN = /\[来源:([^\]]+)\]/g

/**
 * 把 `[来源:id]` 标记转换成 markdown 链接，这样它们能作为内联节点在 markdown 解析中存活下来。
 * 这里用 `#` 开头的伪 href，是因为 react-markdown 默认的 urlTransform 会出于 XSS 防护
 * 剥离未知的 URI scheme（例如 `citation:`），但会原样保留片段链接（fragment link）。
 */
function preprocessCitations(content: string) {
  return content.replace(CITATION_PATTERN, (_match, sourceId) => `[来源:${sourceId}](#citation:${encodeURIComponent(sourceId)})`)
}

export function ThinkingDisclosure({
  thinking,
  label = '查看 AI 推理过程',
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
    <div className="my-1.5">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setManualExpanded(!expanded)}
        className="flex items-center gap-1 text-caption text-neutral-placeholder transition-colors hover:text-neutral-text-secondary"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span className={pulsing ? 'animate-pulse' : undefined}>{label}</span>
      </button>
      {expanded && (
        <div className="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap rounded-btn border border-neutral-border bg-neutral-border/20 px-3 py-2 text-caption leading-relaxed text-neutral-text-secondary">
          {thinking}
        </div>
      )}
    </div>
  )
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
 * memo 是这里真正治"卡顿"的一环：IntakeChat.tsx 的打字机队列每帧都会更新
 * Zustand store 里当前会话的 streamingContent，而 Zustand 的
 * selector 一旦返回新的会话对象引用，整个 IntakeChat 组件树都会重新渲染——
 * 如果 ChatMessageBubble 不做记忆化，意味着对话里*已经生成完*的每一条历史消息，
 * 也会跟着每帧重新执行一遍、重新跑一遍 ReactMarkdown 解析，纯属浪费，且随对话
 * 变长而线性变差。message 对象在 store 里只追加不修改，引用稳定，默认浅比较
 * 就能正确跳过没变化的历史消息。
 */
function ChatMessageBubble({ message, showReasoning = false }: Props) {
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
        {showReasoning && message.thinking && <ThinkingDisclosure thinking={message.thinking} />}
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents(message.citations)}>
          {preprocessCitations(message.content)}
        </ReactMarkdown>
      </div>
    </div>
  )
}

export default memo(ChatMessageBubble)

/** AI 流式生成回复时显示的打字指示器 */
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
 * `wj-stream-fade-in` 只在外层气泡挂载时触发一次（这个组件的生命周期就是
 * 一轮流式输出的时长）——文字增长本身的平滑感来自 IntakeChat.tsx 里基于
 * requestAnimationFrame 的打字机队列，而不是每次更新都重新触发一次 CSS 动画
 * （逐字符粒度地重触发动画看起来是闪烁，不是平滑）。
 *
 * 对 `content` 用 `useDeferredValue` 在回复变长时（表格、多段落回答）才真正
 * 见效：每一帧都把*目前累积的全部* markdown 字符串重新解析一遍，是随长度线性
 * 增长的实际开销，而一次同步渲染耗时超过一帧，正是真正造成掉帧的原因——
 * 靠 CSS 动画是补不回来的。用 deferred 让 React 在负载高时可以降低这次重新
 * 解析的优先级/打断它，而不是阻塞这一帧，同时光标仍然立刻跟随最新值。
 */
export function ChatStreamingBubble({
  content,
  thinking,
  showReasoning = false,
}: {
  content: string
  thinking?: string
  showReasoning?: boolean
}) {
  const deferredContent = useDeferredValue(content)
  return (
    <div className="flex gap-2 items-start wj-stream-fade-in">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-[#1E40AF] to-[#2563EB]
        flex items-center justify-center mt-0.5">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="max-w-[85%] pt-1 text-sm leading-relaxed text-[#0F172A] break-words">
        {showReasoning && thinking && (
          <ThinkingDisclosure
            thinking={thinking}
            label={content ? '查看 AI 推理过程' : 'AI 正在思考…'}
            defaultExpanded={!content}
            pulsing={!content}
          />
        )}
        {content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents([])}>
            {preprocessCitations(deferredContent)}
          </ReactMarkdown>
        ) : !showReasoning || !thinking ? (
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
