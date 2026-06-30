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
        brand: {
          primary: '#1E40AF',
          secondary: '#0D9488',
        },
        risk: {
          high: '#DC2626',
          'high-bg': '#FEF2F2',
          medium: '#D97706',
          'medium-bg': '#FFFBEB',
          low: '#16A34A',
          'low-bg': '#F0FDF4',
          info: '#2563EB',
          'info-bg': '#EFF6FF',
        },
        neutral: {
          page: '#F8FAFC',
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
      },
    },
  },
  plugins: [],
}

export default config
