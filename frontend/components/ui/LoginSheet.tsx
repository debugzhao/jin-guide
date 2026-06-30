'use client'

import { useState } from 'react'
import Modal from './Modal'
import Button from './Button'
import { api } from '@/lib/api'

interface LoginSheetProps {
  isOpen: boolean
  onClose: () => void
  onSuccess?: () => void
}

export default function LoginSheet({ isOpen, onClose, onSuccess }: LoginSheetProps) {
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [codeSent, setCodeSent] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const sendCode = () => {
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      setError('请输入有效的手机号')
      return
    }
    setError('')
    setCodeSent(true)
    setCountdown(60)
    const t = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) { clearInterval(t); return 0 }
        return c - 1
      })
    }, 1000)
  }

  const handleSubmit = async () => {
    if (!codeSent || code.length < 4) {
      setError('请输入验证码')
      return
    }
    setError('')
    setLoading(true)
    try {
      await api.createSession()
      onSuccess?.()
      onClose()
    } catch {
      setError('登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="登录 / 注册">
      <div className="space-y-5">
        <p className="text-sm leading-6 text-[#64748B]">输入手机号，免费使用问津 AI 志愿助理</p>

        {/* Phone */}
        <div>
          <label className="mb-2 block text-sm font-medium text-[#0F172A]">手机号</label>
          <input
            type="tel"
            value={phone}
            onChange={e => setPhone(e.target.value)}
            placeholder="请输入手机号"
            maxLength={11}
            className="h-11 w-full rounded-btn border border-[#E2E8F0] bg-white px-3 text-sm text-[#0F172A] outline-none transition focus:border-[#1E40AF] focus:ring-2 focus:ring-[#1E40AF]/20"
          />
        </div>

        {/* Code */}
        <div>
          <label className="mb-2 block text-sm font-medium text-[#0F172A]">验证码</label>
          <div className="flex gap-3">
            <input
              type="text"
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="6 位验证码"
              className="h-11 min-w-0 flex-1 rounded-btn border border-[#E2E8F0] bg-white px-3 text-sm text-[#0F172A] outline-none transition focus:border-[#1E40AF] focus:ring-2 focus:ring-[#1E40AF]/20"
            />
            <button
              type="button"
              onClick={sendCode}
              disabled={countdown > 0}
              className="h-11 shrink-0 rounded-btn border border-[#E2E8F0] px-4 text-sm font-medium text-[#1E40AF] transition hover:bg-[#EFF6FF] disabled:cursor-not-allowed disabled:bg-white disabled:text-[#94A3B8]"
            >
              {countdown > 0 ? `${countdown}s` : '获取验证码'}
            </button>
          </div>
        </div>

        {error && <p className="text-xs text-[#DC2626]">{error}</p>}

        <Button className="h-11 w-full text-base" onClick={handleSubmit} disabled={loading}>
          {loading ? '登录中…' : '登录'}
        </Button>

        <p className="text-center text-xs text-[#94A3B8]">
          登录即同意《用户协议》和《隐私政策》
        </p>
      </div>
    </Modal>
  )
}
