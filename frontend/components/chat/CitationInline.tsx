'use client'

import { ExternalLink } from 'lucide-react'
import { useState } from 'react'

interface Props {
  sourceId: string
  text: string
}

export default function CitationInline({ sourceId, text }: Props) {
  const [hovered, setHovered] = useState(false)

  return (
    <span className="relative inline-block">
      <a
        href={`/sources/${sourceId}`}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 ml-0.5 text-[10px] font-medium
          bg-blue-50 text-blue-600 border border-blue-200 rounded-full hover:bg-blue-100
          transition-colors cursor-pointer no-underline"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <ExternalLink className="w-2.5 h-2.5" />
        <span>来源</span>
      </a>
      {hovered && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-50
          bg-gray-900 text-white text-[10px] px-2 py-1 rounded whitespace-nowrap pointer-events-none">
          {text}
        </span>
      )}
    </span>
  )
}
