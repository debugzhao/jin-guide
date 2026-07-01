'use client'

import { Bot } from 'lucide-react'
import type { ChatMessage } from '@/types'
import CitationInline from './CitationInline'

interface Props {
  message: ChatMessage
}

/** Renders the message text and injects CitationInline for [来源:id] references. */
function renderContentWithCitations(content: string, citations: { source_id: string; text: string }[]) {
  const parts = content.split(/(\[来源:[^\]]+\])/g)
  return parts.map((part, i) => {
    const match = part.match(/^\[来源:([^\]]+)\]$/)
    if (match) {
      const sourceId = match[1]
      const citation = citations.find((c) => c.source_id === sourceId)
      return (
        <CitationInline
          key={i}
          sourceId={sourceId}
          text={citation?.text ?? `来源 ${sourceId}`}
        />
      )
    }
    return <span key={i}>{part}</span>
  })
}

export default function ChatMessageBubble({ message }: Props) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] px-3.5 py-2.5 rounded-2xl rounded-tr-sm
          bg-blue-600 text-white text-sm leading-relaxed break-words">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-2 items-start">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600
        flex items-center justify-center mt-0.5">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-tl-sm
        bg-white border border-gray-100 shadow-sm text-sm leading-relaxed text-gray-800 break-words">
        {renderContentWithCitations(message.content, message.citations)}
      </div>
    </div>
  )
}

/** Typing indicator shown while AI is streaming */
export function ChatTypingIndicator() {
  return (
    <div className="flex gap-2 items-start">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600
        flex items-center justify-center">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-sm bg-white border border-gray-100 shadow-sm">
        <div className="flex gap-1 items-center h-4">
          <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:0ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:150ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  )
}

/** Streaming bubble shows partial content while tokens arrive */
export function ChatStreamingBubble({ content }: { content: string }) {
  return (
    <div className="flex gap-2 items-start">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600
        flex items-center justify-center mt-0.5">
        <Bot className="w-4 h-4 text-white" />
      </div>
      <div className="max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-tl-sm
        bg-white border border-gray-100 shadow-sm text-sm leading-relaxed text-gray-800 break-words">
        {content || (
          <div className="flex gap-1 items-center h-4">
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:300ms]" />
          </div>
        )}
        <span className="inline-block w-0.5 h-4 bg-blue-500 animate-pulse ml-0.5 align-text-bottom" />
      </div>
    </div>
  )
}
