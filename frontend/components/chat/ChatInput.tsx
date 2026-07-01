'use client'

import { Send } from 'lucide-react'
import { useRef, useState, KeyboardEvent } from 'react'

interface Props {
  onSend: (message: string) => void
  disabled?: boolean
  placeholder?: string
  maxLength?: number
}

export default function ChatInput({
  onSend,
  disabled = false,
  placeholder = '输入问题，Enter 发送…',
  maxLength = 200,
}: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = value.trim().length > 0 && !disabled

  const handleSend = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }

  return (
    <div className="border-t border-gray-100 bg-white px-3 py-2.5">
      <div className="flex items-end gap-2 bg-gray-50 rounded-xl border border-gray-200
        focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100
        transition-all px-3 py-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          disabled={disabled}
          placeholder={disabled ? '发送中…' : placeholder}
          maxLength={maxLength}
          rows={1}
          className="flex-1 bg-transparent resize-none text-sm text-gray-800 placeholder-gray-400
            outline-none min-h-[20px] max-h-[120px] leading-5 disabled:opacity-50"
        />
        <button
          onClick={handleSend}
          disabled={!canSend}
          className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center
            bg-blue-600 hover:bg-blue-700 disabled:bg-gray-200 transition-colors mb-0.5"
          aria-label="发送"
        >
          <Send className="w-3.5 h-3.5 text-white disabled:text-gray-400" />
        </button>
      </div>
      {value.length > maxLength * 0.8 && (
        <p className="text-[10px] text-gray-400 text-right mt-1 pr-1">
          {value.length}/{maxLength}
        </p>
      )}
    </div>
  )
}
