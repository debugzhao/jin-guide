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
        // LiteLLM 式深紫黑克制风格 (docs/frontend-prd-v2.md §3.2, docs/frontend-style.md)
        brand: {
          primary: '#A78BFA',
          secondary: '#2DD4BF',
        },
        // 背景与层次：基色 + 装饰光晕 + 玻璃卡片
        surface: {
          base: '#040128',
          glow: 'rgba(139, 124, 246, 0.12)',
          card: 'rgba(255, 255, 255, 0.04)',
          'card-border': 'rgba(255, 255, 255, 0.10)',
          overlay: 'rgba(10, 8, 38, 0.92)',
        },
        // 风险等级色：保留红/橙/绿/蓝语义色相，降低饱和度+半透明背景以适配深色底
        risk: {
          high: '#F2A9A9',
          'high-bg': 'rgba(242, 169, 169, 0.12)',
          'high-border': 'rgba(242, 169, 169, 0.32)',
          medium: '#EFC48A',
          'medium-bg': 'rgba(239, 196, 138, 0.12)',
          'medium-border': 'rgba(239, 196, 138, 0.32)',
          low: '#8FE0B7',
          'low-bg': 'rgba(143, 224, 183, 0.12)',
          'low-border': 'rgba(143, 224, 183, 0.32)',
          info: '#A9B4F5',
          'info-bg': 'rgba(169, 180, 245, 0.12)',
          'info-border': 'rgba(169, 180, 245, 0.32)',
        },
        // 中性色：深底浅字（与浅色主题相反）
        neutral: {
          page: '#040128',
          card: 'rgba(255, 255, 255, 0.04)',
          'text-primary': '#F1F5F9',
          'text-secondary': '#9CA3C4',
          placeholder: '#6B7280',
          border: 'rgba(255, 255, 255, 0.10)',
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
        card: '0 8px 24px rgba(0, 0, 0, 0.35)',
      },
    },
  },
  plugins: [],
}

export default config
