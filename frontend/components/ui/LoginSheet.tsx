'use client'

import { useState } from 'react'
import Modal from './Modal'
import Button from './Button'
import { api } from '@/lib/api'

type Mode = 'login' | 'register'

interface LoginSheetProps {
  isOpen: boolean
  onClose: () => void
  onSuccess?: () => void
}

export default function LoginSheet({ isOpen, onClose, onSuccess }: LoginSheetProps) {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [codeSent, setCodeSent] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const resetForm = () => {
    setEmail('')
    setPassword('')
    setCode('')
    setCodeSent(false)
    setCountdown(0)
    setError('')
  }

  const switchMode = (m: Mode) => {
    resetForm()
    setMode(m)
  }

  const handleSendCode = async () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('请输入有效的邮箱地址')
      return
    }
    setError('')
    try {
      await api.sendCode(email)
      setCodeSent(true)
      setCountdown(60)
      const t = setInterval(() => {
        setCountdown(c => {
          if (c <= 1) { clearInterval(t); return 0 }
          return c - 1
        })
      }, 1000)
    } catch {
      setError('发送验证码失败，请稍后重试')
    }
  }

  const handleLogin = async () => {
    if (!email || !password) {
      setError('请填写邮箱和密码')
      return
    }
    setError('')
    setLoading(true)
    try {
      await api.login({ email, password })
      onSuccess?.()
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : ''
      setError(msg.includes('401') ? '邮箱或密码不正确' : '登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async () => {
    if (!email || !code || !password) {
      setError('请填写所有字段')
      return
    }
    if (password.length < 8) {
      setError('密码至少 8 位')
      return
    }
    setError('')
    setLoading(true)
    try {
      await api.register({ email, code, password })
      onSuccess?.()
      onClose()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : ''
      if (msg.includes('409')) setError('该邮箱已注册，请直接登录')
      else if (msg.includes('400')) setError('验证码不正确或已过期')
      else setError('注册失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const inputCls = 'h-11 w-full rounded-btn border border-[#E2E8F0] bg-white px-3 text-sm text-[#0F172A] outline-none transition focus:border-[#1E40AF] focus:ring-2 focus:ring-[#1E40AF]/20'

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={mode === 'login' ? '登录' : '注册'}>
      <div className="space-y-5">
        {/* 邮箱 */}
        <div>
          <label className="mb-2 block text-sm font-medium text-[#0F172A]">邮箱</label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="example@email.com"
            className={inputCls}
          />
        </div>

        {/* 注册时显示：验证码 */}
        {mode === 'register' && (
          <div>
            <label className="mb-2 block text-sm font-medium text-[#0F172A]">邮箱验证码</label>
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
                onClick={handleSendCode}
                disabled={countdown > 0}
                className="h-11 shrink-0 rounded-btn border border-[#E2E8F0] px-4 text-sm font-medium text-[#1E40AF] transition hover:bg-[#EFF6FF] disabled:cursor-not-allowed disabled:text-[#94A3B8]"
              >
                {countdown > 0 ? `${countdown}s` : codeSent ? '重新发送' : '获取验证码'}
              </button>
            </div>
          </div>
        )}

        {/* 密码 */}
        <div>
          <label className="mb-2 block text-sm font-medium text-[#0F172A]">密码</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={mode === 'register' ? '至少 8 位' : '请输入密码'}
            className={inputCls}
          />
        </div>

        {error && <p className="text-xs text-[#DC2626]">{error}</p>}

        <Button
          className="h-11 w-full text-base"
          onClick={mode === 'login' ? handleLogin : handleRegister}
          disabled={loading}
        >
          {loading ? (mode === 'login' ? '登录中…' : '注册中…') : (mode === 'login' ? '登录' : '注册')}
        </Button>

        <p className="text-center text-sm text-[#64748B]">
          {mode === 'login' ? (
            <>还没有账号？{' '}
              <button type="button" onClick={() => switchMode('register')} className="font-medium text-[#1E40AF] hover:underline">
                免费注册
              </button>
            </>
          ) : (
            <>已有账号？{' '}
              <button type="button" onClick={() => switchMode('login')} className="font-medium text-[#1E40AF] hover:underline">
                直接登录
              </button>
            </>
          )}
        </p>

        <p className="text-center text-xs text-[#94A3B8]">登录或注册即同意《用户协议》和《隐私政策》</p>
      </div>
    </Modal>
  )
}
