import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatScore(score: number): string {
  return score.toString()
}

export function formatRank(rank: number): string {
  return rank.toLocaleString('zh-CN')
}

export function formatSafetyScore(score: number): string {
  return `${score}%`
}

export function getRiskLevelLabel(level: string): string {
  const labels: Record<string, string> = {
    high: '高风险',
    medium: '中等风险',
    low: '低风险',
    info: '提示',
  }
  return labels[level] ?? level
}

export function getPlanTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    conservative: '保守型',
    balanced: '均衡型',
    aggressive: '进取型',
  }
  return labels[type] ?? type
}

export function getTierLabel(tier: string): string {
  const labels: Record<string, string> = {
    rush: '冲',
    target: '稳',
    safe: '保',
  }
  return labels[tier] ?? tier
}
