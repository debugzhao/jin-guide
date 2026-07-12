import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // 纯白背景 + 克制配色，对齐 docs/wenjin-agent-prototype.html 的 :root 变量
        brand: {
          primary: '#1E40AF',
          secondary: '#0D9488',
        },
        // 背景与层次：纯白页面 + 白色卡片
        surface: {
          base: '#FFFFFF',
          glow: 'rgba(30, 64, 175, 0.06)',
          card: '#FFFFFF',
          'card-border': '#E2E8F0',
          overlay: 'rgba(15, 23, 42, 0.45)',
        },
        // 风险等级色：红/橙/绿/蓝语义色相，浅色背景下用饱和文字色 + 极浅背景
        risk: {
          high: '#DC2626',
          'high-bg': '#FEF2F2',
          'high-border': '#FECACA',
          medium: '#D97706',
          'medium-bg': '#FFFBEB',
          'medium-border': '#FDE68A',
          low: '#16A34A',
          'low-bg': '#F0FDF4',
          'low-border': '#BBF7D0',
          info: '#2563EB',
          'info-bg': '#EFF6FF',
          'info-border': '#BFDBFE',
        },
        // 中性色：白底深字
        neutral: {
          page: '#FFFFFF',
          card: '#FFFFFF',
          'text-primary': '#0F172A',
          'text-secondary': '#64748B',
          placeholder: '#94A3B8',
          border: '#E2E8F0',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'PingFang SC', 'Noto Sans SC', 'Helvetica Neue', 'sans-serif'],
      },
      borderRadius: {
        card: '12px',
        btn: '8px',
        tag: '4px',
        bubble: '16px',
      },
      boxShadow: {
        card: '0 1px 3px rgba(15, 23, 42, 0.08)',
      },
    },
  },
  plugins: [],
}

export default config
