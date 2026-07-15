'use client'

import { Bot } from 'lucide-react'
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
    h2: ({ children }) => <h2 className="mb-2 mt-1 text-[15px] font-semibold">{children}</h2>,
    h3: ({ children }) => <h3 className="mb-1.5 mt-1 text-sm font-semibold">{children}</h3>,
    code: ({ children }) => (
      <code className="rounded bg-neutral-border/60 px-1 py-0.5 font-mono text-[13px]">{children}</code>
    ),
    pre: ({ children }) => (
      <pre className="mb-2 last:mb-0 overflow-x-auto rounded-lg bg-[#0F172A] p-3 text-[13px] text-white">
        {children}
      </pre>
    ),
    table: ({ children }) => (
      <div className="mb-2 last:mb-0 overflow-x-auto">
        <table className="min-w-full border-collapse text-[13px]">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-neutral-border/40">{children}</thead>,
    th: ({ children }) => (
      <th className="border border-neutral-border px-2 py-1 text-left font-semibold">{children}</th>
    ),
    td: ({ children }) => <td className="border border-neutral-border px-2 py-1">{children}</td>,
  }
}

export default function ChatMessageBubble({ message }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] px-3.5 py-2.5 rounded-2xl rounded-tr-sm
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
      <div className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-tl-sm
        wj-glass-card text-sm leading-relaxed text-[#0F172A] break-words">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents(message.citations)}>
          {preprocessCitations(message.content)}
        </ReactMarkdown>
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
      <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-sm wj-glass-card">
        <div className="flex gap-1 items-center h-4">
          <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:0ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:150ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  )
}

/** Streaming bubble shows partial content while tokens arrive */
export function ChatStreamingBubble({ content }: { content: string }) {
  return (
    <div className="flex gap-2 items-start">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-[#1E40AF] to-[#2563EB]
        flex items-center justify-center mt-0.5">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-tl-sm
        wj-glass-card text-sm leading-relaxed text-[#0F172A] break-words">
        {content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildMarkdownComponents([])}>
            {preprocessCitations(content)}
          </ReactMarkdown>
        ) : (
          <div className="flex gap-1 items-center h-4">
            <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-[#94A3B8] animate-bounce [animation-delay:300ms]" />
          </div>
        )}
        <span className="inline-block w-0.5 h-4 bg-[#1E40AF] animate-pulse ml-0.5 align-text-bottom" />
      </div>
    </div>
  )
}
