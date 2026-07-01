import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { PlanType } from '@/types'

interface AssessFormData {
  province?: string
  batch?: string
  score?: number
  rank?: number
  subjects?: string[]
  gender?: string
  hasPhysicalLimits?: boolean
}

interface AppStore {
  profileId: string | null
  setProfileId: (id: string) => void
  currentTab: PlanType
  setCurrentTab: (tab: PlanType) => void
  wizardStep: number
  setWizardStep: (step: number) => void
  assessFormData: AssessFormData
  setAssessFormData: (data: AssessFormData) => void
  // 复核员工作台身份标识：MVP 阶段暂无独立的复核员账号体系，
  // 用本地持久化的名字代替，仅用于 claim/提交结论时标注 reviewer_id
  reviewerId: string | null
  setReviewerId: (id: string | null) => void
}

export const useAppStore = create<AppStore>()(
  persist(
    (set) => ({
      profileId: null,
      setProfileId: (id) => set({ profileId: id }),
      currentTab: 'balanced',
      setCurrentTab: (tab) => set({ currentTab: tab }),
      wizardStep: 1,
      setWizardStep: (step) => set({ wizardStep: step }),
      assessFormData: {},
      setAssessFormData: (data) => set({ assessFormData: data }),
      reviewerId: null,
      setReviewerId: (id) => set({ reviewerId: id }),
    }),
    {
      name: 'wenjin-store',
    }
  )
)
