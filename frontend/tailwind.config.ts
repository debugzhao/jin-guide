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
      // 字号阶梯对齐 docs/frontend-prd-v2.md §3.3；额外的 micro 档覆盖时间戳/角标等
      // 比"次要文字"更小的场景，PRD 5 级表未定义，是 §3.6 落地时按实际用量补的第 6 档。
      fontSize: {
        micro: ['11px', '16px'],
        caption: ['13px', '18px'],
        body: ['15px', '22px'],
        subtitle: ['17px', '24px'],
        title: ['20px', '28px'],
        emphasis: ['22px', '28px'],
      },
      borderRadius: {
        card: '12px',
        btn: '8px',
        tag: '4px',
        bubble: '16px',
      },
      // 阴影三级梯度（§3.6）：card 贴合内容流的常规卡片/气泡；floating 用于输入框、
      // 悬浮按钮、下拉菜单这类"浮在页面上"的元素；modal 用于弹层/抽屉，投影最强。
      boxShadow: {
        card: '0 1px 3px rgba(15, 23, 42, 0.08)',
        floating: '0 4px 16px rgba(15, 23, 42, 0.12)',
        modal: '0 12px 32px rgba(15, 23, 42, 0.18)',
      },
    },
  },
  plugins: [],
}

export default config
